package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/blackjack/webcam"
)

type CameraInfo struct {
	Device  string `json:"device"`
	Product string `json:"product"`
}

type CameraStream struct {
	devicePath string
	product    string
	cam        *webcam.Webcam
	running    bool
	mutex      sync.RWMutex
	lastFrame  []byte
}

type StreamingServer struct {
	cameras    [2]*CameraStream
	httpServer *http.Server
}

func getCameraList() ([]CameraInfo, error) {
	cmd := exec.Command("bash", "get_camera.sh")
	output, err := cmd.Output()
	if err != nil {
		return nil, err
	}

	// Parse JSON from the last line
	lines := string(output)
	var jsonLine string
	for i := len(lines) - 1; i >= 0; i-- {
		if lines[i] == '\n' {
			jsonLine = lines[i+1:]
			break
		}
	}

	if jsonLine == "" {
		jsonLine = lines
	}

	var cameras []CameraInfo
	err = json.Unmarshal([]byte(jsonLine), &cameras)
	if err != nil {
		return nil, err
	}

	return cameras, nil
}

func NewCameraStream(devicePath, product string) *CameraStream {
	return &CameraStream{
		devicePath: devicePath,
		product:    product,
		running:    false,
	}
}

func (cs *CameraStream) Initialize() error {
	log.Printf("Initializing camera: %s (%s)", cs.devicePath, cs.product)
	
	cam, err := webcam.Open(cs.devicePath)
	if err != nil {
		return err
	}
	cs.cam = cam

	// Try to set 1280x720 resolution
	_, _, _, err = cs.cam.SetImageFormat(webcam.PixelFormat(1196444237), 1280, 720) // MJPEG
	if err != nil {
		// Try YUYV as fallback
		_, _, _, err = cs.cam.SetImageFormat(webcam.PixelFormat(1448695129), 1280, 720) // YUYV
		if err != nil {
			cam.Close()
			return err
		}
	}

	// Set FPS
	cs.cam.SetFramerate(30.0)

	// Start streaming
	err = cs.cam.StartStreaming()
	if err != nil {
		cam.Close()
		return err
	}

	cs.running = true
	log.Printf("Camera %s initialized successfully", cs.devicePath)
	return nil
}

func (cs *CameraStream) StartCapture() {
	go func() {
		for cs.running {
			err := cs.cam.WaitForFrame(5)
			if err != nil {
				continue
			}

			frame, err := cs.cam.ReadFrame()
			if err == nil && len(frame) > 0 {
				cs.mutex.Lock()
				cs.lastFrame = frame
				cs.mutex.Unlock()
			}
		}
	}()
}

func (cs *CameraStream) GetFrame() []byte {
	cs.mutex.RLock()
	defer cs.mutex.RUnlock()
	return cs.lastFrame
}

func (cs *CameraStream) Close() {
	cs.running = false
	if cs.cam != nil {
		cs.cam.StopStreaming()
		cs.cam.Close()
	}
}

func NewStreamingServer() *StreamingServer {
	// Get camera list from shell script
	cameras, err := getCameraList()
	if err != nil {
		log.Fatalf("Failed to get camera list: %v", err)
	}

	server := &StreamingServer{}

	// Initialize cameras
	for i, camera := range cameras {
		if i >= 2 {
			break
		}

		stream := NewCameraStream(camera.Device, camera.Product)
		err := stream.Initialize()
		if err != nil {
			log.Printf("Failed to initialize camera %s: %v", camera.Device, err)
			continue
		}
		server.cameras[i] = stream
		stream.StartCapture()
	}

	return server
}

func (ss *StreamingServer) GenerateMJPEG(cameraID int) gin.HandlerFunc {
	return func(c *gin.Context) {
		if cameraID < 0 || cameraID >= len(ss.cameras) || ss.cameras[cameraID] == nil {
			http.Error(c.Writer, "Camera not found", http.StatusNotFound)
			return
		}

		c.Writer.Header().Set("Content-Type", "multipart/x-mixed-replace; boundary=frame")
		c.Writer.Header().Set("Cache-Control", "no-cache, no-store, must-revalidate")
		c.Writer.Header().Set("Pragma", "no-cache")
		c.Writer.Header().Set("Expires", "0")

		camera := ss.cameras[cameraID]

		for {
			select {
			case <-c.Request.Context().Done():
				return
			default:
				frame := camera.GetFrame()
				if frame != nil {
					c.Writer.Write([]byte("--frame\r\nContent-Type: image/jpeg\r\n\r\n"))
					c.Writer.Write(frame)
					c.Writer.Write([]byte("\r\n\r\n"))
				}
				time.Sleep(33 * time.Millisecond) // ~30 FPS
			}
		}
	}
}

func (ss *StreamingServer) SetupRoutes() *gin.Engine {
	gin.SetMode(gin.ReleaseMode)
	router := gin.New()

	// Root endpoint
	router.GET("/", func(c *gin.Context) {
		cameraInfo := make([]gin.H, 0)
		for i, cam := range ss.cameras {
			if cam != nil {
				cameraInfo = append(cameraInfo, gin.H{
					"camera_id": i,
					"device":    cam.devicePath,
					"product":   cam.product,
				})
			}
		}

		c.JSON(200, gin.H{
			"message": "USB Camera Streaming Server",
			"cameras": cameraInfo,
		})
	})

	// Streaming endpoints
	router.GET("/camera/0", ss.GenerateMJPEG(0))
	router.GET("/camera/1", ss.GenerateMJPEG(1))

	// Camera list endpoint
	router.GET("/cameras", func(c *gin.Context) {
		cameras, err := getCameraList()
		if err != nil {
			c.JSON(500, gin.H{"error": err.Error()})
			return
		}
		c.JSON(200, cameras)
	})

	return router
}

func (ss *StreamingServer) Start(addr string) error {
	router := ss.SetupRoutes()

	ss.httpServer = &http.Server{
		Addr:    addr,
		Handler: router,
	}

	log.Printf("Starting streaming server on %s", addr)
	return ss.httpServer.ListenAndServe()
}

func (ss *StreamingServer) Shutdown() {
	log.Println("Shutting down streaming server...")
	for i, camera := range ss.cameras {
		if camera != nil {
			log.Printf("Closing camera %d (%s)...", i, camera.devicePath)
			camera.Close()
		}
	}

	if ss.httpServer != nil {
		ss.httpServer.Close()
	}
}

func main() {
	// Setup signal handling
	sigs := make(chan os.Signal, 1)
	signal.Notify(sigs, syscall.SIGINT, syscall.SIGTERM)

	server := NewStreamingServer()

	// Start server
	go func() {
		if err := server.Start(":8080"); err != nil && err != http.ErrServerClosed {
			log.Fatalf("Server error: %v", err)
		}
	}()

	log.Println("Server started on :8080")
	log.Println("Endpoints:")
	log.Println("  GET /         - Server info") 
	log.Println("  GET /camera/0 - Stream camera 0")
	log.Println("  GET /camera/1 - Stream camera 1")
	log.Println("  GET /cameras  - List detected cameras")

	// Wait for shutdown signal
	<-sigs
	server.Shutdown()
	log.Println("Server shutdown complete")
}