// rtsp_manager.go
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strconv"
	"sync"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
)

type CameraInfo struct {
	Device  string `json:"device"`
	Product string `json:"product"`
}

type CameraProcess struct {
	info       CameraInfo
	rtspPath   string
	cmd        *exec.Cmd
	startedAt  time.Time
	mutex      sync.Mutex
	restarts   int
	cancelFunc context.CancelFunc
}

type Manager struct {
	cameras map[int]*CameraProcess
	lock    sync.Mutex
}

func NewManager(cameraList []CameraInfo) *Manager {
	m := &Manager{
		cameras: make(map[int]*CameraProcess),
	}
	for i, cam := range cameraList {
		rtspPath := fmt.Sprintf("rtsp://127.0.0.1:8554/cam%d", i)
		m.cameras[i] = &CameraProcess{
			info:     cam,
			rtspPath: rtspPath,
		}
	}
	return m
}

// StartCamera will spawn a gst-rtsp-server test-launch process for the given camera index.
// It uses Jetson hardware encoder nvv4l2h264enc in the pipeline.
func (m *Manager) StartCamera(idx int) error {
	m.lock.Lock()
	cp, ok := m.cameras[idx]
	m.lock.Unlock()
	if !ok {
		return fmt.Errorf("camera %d not found", idx)
	}

	cp.mutex.Lock()
	defer cp.mutex.Unlock()

	if cp.cmd != nil {
		return fmt.Errorf("camera %d already started", idx)
	}

	// Build GStreamer pipeline string. Adjust width/height/framerate/bitrate as needed.
	// If you use CSI camera (nvarguscamerasrc), change the src element accordingly.
	pipeline := fmt.Sprintf("( v4l2src device=%s ! video/x-raw,width=1280,height=720,framerate=30/1 ! nvvidconv ! 'video/x-raw(memory:NVMM),format=NV12' ! nvv4l2h264enc bitrate=2000000 ! h264parse ! rtph264pay name=pay0 pt=96 )", cp.info.Device)

	// test-launch is the sample binary from gst-rtsp-server repo that runs a pipeline as RTSP server.
	// If you don't have test-launch, install gst-rtsp-server or change this to another method.
	ctx, cancel := context.WithCancel(context.Background())
	cmd := exec.CommandContext(ctx, "test-launch", pipeline)
	// send stdout/stderr to files for debugging
	logDir := "./logs"
	os.MkdirAll(logDir, 0755)
	stdoutFile, _ := os.OpenFile(filepath.Join(logDir, fmt.Sprintf("cam%d_stdout.log", idx)), os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	stderrFile, _ := os.OpenFile(filepath.Join(logDir, fmt.Sprintf("cam%d_stderr.log", idx)), os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	cmd.Stdout = stdoutFile
	cmd.Stderr = stderrFile

	// Start the process
	if err := cmd.Start(); err != nil {
		cancel()
		return fmt.Errorf("failed to start test-launch for camera %d: %w", idx, err)
	}

	cp.cmd = cmd
	cp.cancelFunc = cancel
	cp.startedAt = time.Now()
	cp.restarts = 0

	// Monitor in goroutine: wait for exit and cleanup
	go func(index int, p *CameraProcess, stdout, stderr *os.File) {
		err := cmd.Wait()
		stdout.Close()
		stderr.Close()
		p.mutex.Lock()
		p.cmd = nil
		if p.cancelFunc != nil {
			p.cancelFunc()
			p.cancelFunc = nil
		}
		p.mutex.Unlock()
		if err != nil {
			log.Printf("camera %d process exited with error: %v (logs: %s, %s)", index, err, stdout.Name(), stderr.Name())
		} else {
			log.Printf("camera %d process exited cleanly", index)
		}
	}(idx, cp, stdoutFile, stderrFile)

	// Small sleep to let RTSP server up (could poll the RTSP URL in production)
	time.Sleep(400 * time.Millisecond)

	log.Printf("Started camera %d -> %s (pipeline: %s)", idx, cp.rtspPath, pipeline)
	return nil
}

func (m *Manager) StopCamera(idx int) error {
	m.lock.Lock()
	cp, ok := m.cameras[idx]
	m.lock.Unlock()
	if !ok {
		return fmt.Errorf("camera %d not found", idx)
	}

	cp.mutex.Lock()
	defer cp.mutex.Unlock()

	if cp.cmd == nil {
		return fmt.Errorf("camera %d not running", idx)
	}

	// Graceful shutdown via cancel func
	if cp.cancelFunc != nil {
		cp.cancelFunc()
	}

	// give it a short time, then kill
	done := make(chan struct{})
	go func() {
		cp.cmd.Wait()
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(2 * time.Second):
		if cp.cmd.Process != nil {
			cp.cmd.Process.Kill()
		}
	}

	cp.cmd = nil
	cp.cancelFunc = nil
	log.Printf("Stopped camera %d", idx)
	return nil
}

func (m *Manager) Status() []gin.H {
	m.lock.Lock()
	defer m.lock.Unlock()
	out := make([]gin.H, 0, len(m.cameras))
	for i, cp := range m.cameras {
		cp.mutex.Lock()
		running := cp.cmd != nil
		startAt := cp.startedAt
		cp.mutex.Unlock()
		out = append(out, gin.H{
			"id":       i,
			"device":   cp.info.Device,
			"product":  cp.info.Product,
			"rtsp":     cp.rtspPath,
			"running":  running,
			"started":  startAt.Format(time.RFC3339),
		})
	}
	return out
}

func main() {
	// Example: read camera list JSON from env or args; for simplicity we hardcode two cameras here.
	// Replace this with parsing os.Args or config file as you originally had.
	cameraList := []CameraInfo{
		{Device: "/dev/video0", Product: "usbcam0"},
		{Device: "/dev/video1", Product: "usbcam1"},
	}

	manager := NewManager(cameraList)

	// Optionally: auto-start all cameras at boot
	for i := range cameraList {
		if err := manager.StartCamera(i); err != nil {
			log.Printf("warning: failed to autostart camera %d: %v", i, err)
		}
	}

	// Setup HTTP control server
	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.Use(gin.Recovery())

	r.GET("/", func(c *gin.Context) {
		c.JSON(200, gin.H{
			"message": "RTSP Manager",
			"cameras": manager.Status(),
		})
	})

	r.POST("/start/:id", func(c *gin.Context) {
		idStr := c.Param("id")
		id, _ := strconv.Atoi(idStr)
		if err := manager.StartCamera(id); err != nil {
			c.JSON(500, gin.H{"error": err.Error()})
			return
		}
		c.JSON(200, gin.H{"status": "started", "id": id, "rtsp": manager.cameras[id].rtspPath})
	})

	r.POST("/stop/:id", func(c *gin.Context) {
		idStr := c.Param("id")
		id, _ := strconv.Atoi(idStr)
		if err := manager.StopCamera(id); err != nil {
			c.JSON(500, gin.H{"error": err.Error()})
			return
		}
		c.JSON(200, gin.H{"status": "stopped", "id": id})
	})

	r.GET("/rtsp/:id", func(c *gin.Context) {
		idStr := c.Param("id")
		id, _ := strconv.Atoi(idStr)
		manager.lock.Lock()
		cp, ok := manager.cameras[id]
		manager.lock.Unlock()
		if !ok {
			c.JSON(404, gin.H{"error": "not found"})
			return
		}
		c.JSON(200, gin.H{"rtsp": cp.rtspPath})
	})

	// start HTTP server
	httpSrv := &http.Server{
		Addr:    ":8100",
		Handler: r,
	}

	go func() {
		log.Printf("HTTP control server listening on %s", httpSrv.Addr)
		if err := httpSrv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("http server err: %v", err)
		}
	}()

	// Handle shutdown signals
	sigs := make(chan os.Signal, 1)
	signal.Notify(sigs, syscall.SIGINT, syscall.SIGTERM)
	<-sigs
	log.Println("shutting down...")

	// Stop cameras
	for i := range cameraList {
		_ = manager.StopCamera(i)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	httpSrv.Shutdown(ctx)
	log.Println("bye")
}
