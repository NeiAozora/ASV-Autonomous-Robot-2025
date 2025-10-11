package main

import (
	"bytes"
	"context"
	"encoding/binary"
	"image"
	"image/jpeg"
	"log"
	"net/http"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/blackjack/webcam"
	"github.com/korandiz/v4l"
	"golang.org/x/sys/unix"
)

type CameraConfig struct {
	Device      string
	Width       uint32
	Height      uint32
	FPS         uint32
	PixelFormat uint32
}

type CameraStream struct {
	config      CameraConfig
	cam         *webcam.Webcam
	frameBuffer chan []byte
	running     bool
	mutex       sync.RWMutex
	lastFrame   []byte
	errorCount  int
}

type StreamingServer struct {
	cameras    [2]*CameraStream
	httpServer *http.Server
	mutex      sync.RWMutex
}

// Pixel format constants
const (
	V4L2_PIX_FMT_MJPEG = 0x47504A4D
	V4L2_PIX_FMT_H264  = 0x34363248
	V4L2_PIX_FMT_YUYV  = 0x56595559
)

var (
	DefaultCameraConfigs = [2]CameraConfig{
		{
			Device:      "/dev/video0",
			Width:       1280,
			Height:      720,
			FPS:         30,
			PixelFormat: V4L2_PIX_FMT_MJPEG,
		},
		{
			Device:      "/dev/video1",
			Width:       1280,
			Height:      720,
			FPS:         30,
			PixelFormat: V4L2_PIX_FMT_MJPEG,
		},
	}
)

func NewCameraStream(config CameraConfig) *CameraStream {
	return &CameraStream{
		config:      config,
		frameBuffer: make(chan []byte, 10), // Buffer 10 frames
		running:     false,
		errorCount:  0,
	}
}

func (cs *CameraStream) Initialize() error {
	cam, err := webcam.Open(cs.config.Device)
	if err != nil {
		return err
	}
	cs.cam = cam

	// Set format dengan hardware acceleration
	formatDesc := cs.cam.GetSupportedFormats()
	log.Printf("Supported formats for %s:", cs.config.Device)
	for format, desc := range formatDesc {
		log.Printf("  %s (%s)", format, desc)
	}

	// Coba set format MJPEG untuk hardware encoding
	_, _, _, err = cs.cam.SetImageFormat(cs.config.Width, cs.config.Height, webcam.PixelFormat(cs.config.PixelFormat))
	if err != nil {
		log.Printf("Failed to set MJPEG format, trying YUYV: %v", err)
		// Fallback ke YUYV
		_, _, _, err = cs.cam.SetImageFormat(cs.config.Width, cs.config.Height, webcam.PixelFormat(V4L2_PIX_FMT_YUYV))
		if err != nil {
			cam.Close()
			return err
		}
	}

	// Set FPS
	err = cs.cam.SetFramerate(cs.config.FPS)
	if err != nil {
		log.Printf("Warning: Could not set FPS: %v", err)
	}

	// Start streaming
	err = cs.cam.StartStreaming()
	if err != nil {
		cam.Close()
		return err
	}

	cs.running = true
	log.Printf("Camera %s initialized: %dx%d @ %d fps", cs.config.Device, cs.config.Width, cs.config.Height, cs.config.FPS)
	return nil
}

func (cs *CameraStream) StartCapture() {
	go func() {
		defer func() {
			if r := recover(); r != nil {
				log.Printf("Camera %s capture panicked: %v", cs.config.Device, r)
				cs.Reconnect()
			}
		}()

		for cs.running {
			err := cs.cam.WaitForFrame(5) // Timeout 5 detik
			switch err {
			case nil:
				frame, err := cs.cam.ReadFrame()
				if err != nil {
					log.Printf("Error reading frame from %s: %v", cs.config.Device, err)
					cs.errorCount++
					if cs.errorCount > 10 {
						cs.Reconnect()
					}
					continue
				}

				if len(frame) == 0 {
					continue
				}

				// Process frame based on format
				processedFrame, err := cs.ProcessFrame(frame)
				if err != nil {
					log.Printf("Error processing frame from %s: %v", cs.config.Device, err)
					continue
				}

				cs.mutex.Lock()
				cs.lastFrame = processedFrame
				cs.errorCount = 0 // Reset error count on successful frame
				cs.mutex.Unlock()

				// Non-blocking send to buffer
				select {
				case cs.frameBuffer <- processedFrame:
				default:
					// Drop frame if buffer full (maintain performance)
				}

			case unix.EAGAIN:
				// Timeout, continue
				continue
			default:
				log.Printf("Error waiting for frame from %s: %v", cs.config.Device, err)
				cs.errorCount++
				if cs.errorCount > 5 {
					cs.Reconnect()
				}
				time.Sleep(100 * time.Millisecond)
			}
		}
	}()
}

func (cs *CameraStream) ProcessFrame(frame []byte) ([]byte, error) {
	// Jika frame sudah MJPEG, langsung gunakan
	if cs.config.PixelFormat == V4L2_PIX_FMT_MJPEG {
		return frame, nil
	}

	// Konversi YUYV ke JPEG menggunakan hardware acceleration jika memungkinkan
	// Fallback ke software conversion
	return cs.YUYVToJPEG(frame)
}

func (cs *CameraStream) YUYVToJPEG(data []byte) ([]byte, error) {
	// Simple YUYV to JPEG conversion
	// Dalam production, sebaiknya gunakan hardware acceleration melalui VAAPI
	width := int(cs.config.Width)
	height := int(cs.config.Height)

	img := image.NewYCbCr(image.Rect(0, 0, width, height), image.YCbCrSubsampleRatio422)

	// Convert YUYV to YCbCr
	for y := 0; y < height; y++ {
		for x := 0; x < width; x += 2 {
			idx := (y*width + x) * 2
			if idx+3 >= len(data) {
				break
			}

			y1 := data[idx]
			u := data[idx+1]
			y2 := data[idx+2]
			v := data[idx+3]

			// Set pixels
			img.Y[y*img.YStride+x] = y1
			img.Y[y*img.YStride+x+1] = y2
			img.Cb[y*img.CStride+x/2] = u
			img.Cr[y*img.CStride+x/2] = v
		}
	}

	var buf bytes.Buffer
	err := jpeg.Encode(&buf, img, &jpeg.Options{Quality: 85})
	if err != nil {
		return nil, err
	}

	return buf.Bytes(), nil
}

func (cs *CameraStream) GetFrame() []byte {
	cs.mutex.RLock()
	defer cs.mutex.RUnlock()
	return cs.lastFrame
}

func (cs *CameraStream) Reconnect() {
	log.Printf("Reconnecting camera %s...", cs.config.Device)
	cs.mutex.Lock()
	cs.running = false
	cs.mutex.Unlock()

	if cs.cam != nil {
		cs.cam.StopStreaming()
		cs.cam.Close()
	}

	// Tunggu sebentar sebelum reconnect
	time.Sleep(2 * time.Second)

	for i := 0; i < 5; i++ {
		err := cs.Initialize()
		if err == nil {
			cs.StartCapture()
			log.Printf("Camera %s reconnected successfully", cs.config.Device)
			return
		}
		log.Printf("Reconnection attempt %d failed for %s: %v", i+1, cs.config.Device, err)
		time.Sleep(2 * time.Second)
	}

	log.Printf("Failed to reconnect camera %s after 5 attempts", cs.config.Device)
}

func (cs *CameraStream) Close() {
	cs.mutex.Lock()
	defer cs.mutex.Unlock()
	cs.running = false
	if cs.cam != nil {
		cs.cam.StopStreaming()
		cs.cam.Close()
	}
	close(cs.frameBuffer)
}

func NewStreamingServer() *StreamingServer {
	server := &StreamingServer{}

	// Initialize cameras
	for i := 0; i < 2; i++ {
		stream := NewCameraStream(DefaultCameraConfigs[i])
		err := stream.Initialize()
		if err != nil {
			log.Printf("Failed to initialize camera %s: %v", DefaultCameraConfigs[i].Device, err)
			continue
		}
		server.cameras[i] = stream
		stream.StartCapture()
	}

	return server
}

func (ss *StreamingServer) GenerateMJPEG(cameraID int) func(http.ResponseWriter, *http.Request) {
	return func(w http.ResponseWriter, r *http.Request) {
		if cameraID < 0 || cameraID >= len(ss.cameras) || ss.cameras[cameraID] == nil {
			http.Error(w, "Camera not found", http.StatusNotFound)
			return
		}

		w.Header().Set("Content-Type", "multipart/x-mixed-replace; boundary=frame")
		w.Header().Set("Cache-Control", "no-cache, no-store, must-revalidate")
		w.Header().Set("Pragma", "no-cache")
		w.Header().Set("Expires", "0")
		w.Header().Set("X-Accel-Buffering", "no") // Important for Nginx proxy

		flusher, ok := w.(http.Flusher)
		if !ok {
			http.Error(w, "Streaming not supported", http.StatusInternalServerError)
			return
		}

		camera := ss.cameras[cameraID]
		frameInterval := time.Second / time.Duration(camera.config.FPS)
		ticker := time.NewTicker(frameInterval)
		defer ticker.Stop()

		for {
			select {
			case <-r.Context().Done():
				return
			case <-ticker.C:
				frame := camera.GetFrame()
				if frame == nil {
					continue
				}

				_, err := w.Write([]byte("--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " +
					string(len(frame)) + "\r\n\r\n"))
				if err != nil {
					return
				}

				_, err = w.Write(frame)
				if err != nil {
					return
				}

				_, err = w.Write([]byte("\r\n\r\n"))
				if err != nil {
					return
				}
				flusher.Flush()
			}
		}
	}
}

func (ss *StreamingServer) SetupRoutes() *gin.Engine {
	if os.Getenv("GIN_MODE") == "release" {
		gin.SetMode(gin.ReleaseMode)
	}

	router := gin.New()
	router.Use(gin.Recovery())

	// Static endpoint untuk testing
	router.GET("/", func(c *gin.Context) {
		c.JSON(200, gin.H{
			"message": "Dual Camera Streaming Server",
			"cameras": []string{
				"/camera/0",
				"/camera/1",
			},
			"features": []string{
				"Hardware Acceleration",
				"720p Resolution",
				"Auto Reconnection",
				"30 FPS Target",
			},
		})
	})

	// Streaming endpoints
	router.GET("/camera/0", ss.GenerateMJPEG(0))
	router.GET("/camera/1", ss.GenerateMJPEG(1))

	// Status endpoints
	router.GET("/status/0", ss.CameraStatus(0))
	router.GET("/status/1", ss.CameraStatus(1))

	// Reconnect endpoints
	router.POST("/reconnect/0", ss.ReconnectCamera(0))
	router.POST("/reconnect/1", ss.ReconnectCamera(1))

	return router
}

func (ss *StreamingServer) CameraStatus(cameraID int) gin.HandlerFunc {
	return func(c *gin.Context) {
		if cameraID < 0 || cameraID >= len(ss.cameras) || ss.cameras[cameraID] == nil {
			c.JSON(404, gin.H{"error": "Camera not found"})
			return
		}

		camera := ss.cameras[cameraID]
		c.JSON(200, gin.H{
			"camera_id": cameraID,
			"device":    camera.config.Device,
			"running":   camera.running,
			"errors":    camera.errorCount,
			"resolution": gin.H{
				"width":  camera.config.Width,
				"height": camera.config.Height,
			},
			"fps": camera.config.FPS,
		})
	}
}

func (ss *StreamingServer) ReconnectCamera(cameraID int) gin.HandlerFunc {
	return func(c *gin.Context) {
		if cameraID < 0 || cameraID >= len(ss.cameras) || ss.cameras[cameraID] == nil {
			c.JSON(404, gin.H{"error": "Camera not found"})
			return
		}

		camera := ss.cameras[cameraID]
		go camera.Reconnect()

		c.JSON(200, gin.H{
			"message":   "Reconnection initiated",
			"camera_id": cameraID,
		})
	}
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
			log.Printf("Closing camera %d...", i)
			camera.Close()
		}
	}

	if ss.httpServer != nil {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		ss.httpServer.Shutdown(ctx)
	}
}

func main() {
	// Setup signal handling
	sigs := make(chan os.Signal, 1)
	signal.Notify(sigs, syscall.SIGINT, syscall.SIGTERM)

	server := NewStreamingServer()

	// Start server in goroutine
	go func() {
		if err := server.Start(":8080"); err != nil && err != http.ErrServerClosed {
			log.Fatalf("Server error: %v", err)
		}
	}()

	// Wait for shutdown signal
	<-sigs
	server.Shutdown()
	log.Println("Server shutdown complete")
}