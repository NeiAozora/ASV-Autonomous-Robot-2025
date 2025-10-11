package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
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
		return fmt.Errorf("failed to open camera %s: %v", cs.devicePath, err)
	}
	cs.cam = cam

	// Try MJPEG first, then YUYV as fallback
	_, _, _, err = cs.cam.SetImageFormat(webcam.PixelFormat(1196444237), 1280, 720) // MJPEG
	if err != nil {
		log.Printf("MJPEG not supported, trying YUYV: %v", err)
		_, _, _, err = cs.cam.SetImageFormat(webcam.PixelFormat(1448695129), 1280, 720) // YUYV
		if err != nil {
			cam.Close()
			return fmt.Errorf("failed to set image format: %v", err)
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
	log.Printf("Camera %s initialized successfully: 1280x720 @ 30fps", cs.devicePath)
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

func NewStreamingServer(cameraList []CameraInfo) *StreamingServer {
	server := &StreamingServer{}

	// Initialize cameras
	for i, camera := range cameraList {
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
		time.Sleep(500 * time.Millisecond) // Stagger initialization
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
		frameInterval := time.Second / 30 // 30 FPS
		ticker := time.NewTicker(frameInterval)
		defer ticker.Stop()

		for {
			select {
			case <-c.Request.Context().Done():
				return
			case <-ticker.C:
				frame := camera.GetFrame()
				if frame != nil {
					c.Writer.Write([]byte("--frame\r\nContent-Type: image/jpeg\r\n\r\n"))
					c.Writer.Write(frame)
					c.Writer.Write([]byte("\r\n\r\n"))
				}
			}
		}
	}
}

func (ss *StreamingServer) SetupRoutes() *gin.Engine {
	gin.SetMode(gin.ReleaseMode)
	router := gin.New()
	router.Use(gin.Recovery())

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
	// Check if camera list is provided as argument
	if len(os.Args) < 2 {
		log.Fatal("Usage: ./dual-camera-streamer '<camera_json_array>'")
	}

	// Parse camera list from command line argument
	var cameras []CameraInfo
	err := json.Unmarshal([]byte(os.Args[1]), &cameras)
	if err != nil {
		log.Fatalf("Failed to parse camera list: %v", err)
	}

	if len(cameras) == 0 {
		log.Fatal("No cameras provided")
	}

	log.Printf("Loaded %d cameras from command line", len(cameras))
	for i, cam := range cameras {
		log.Printf("Camera %d: %s (%s)", i, cam.Device, cam.Product)
	}

	// Setup signal handling
	sigs := make(chan os.Signal, 1)
	signal.Notify(sigs, syscall.SIGINT, syscall.SIGTERM)

	server := NewStreamingServer(cameras)

	// Start server
	go func() {
		if err := server.Start(":8100"); err != nil && err != http.ErrServerClosed {
			log.Fatalf("Server error: %v", err)
		}
	}()

	log.Println("Server started on :8100")
	log.Println("Endpoints:")
	log.Println("  GET /         - Server info") 
	log.Println("  GET /camera/0 - Stream camera 0")
	log.Println("  GET /camera/1 - Stream camera 1")

	// Wait for shutdown signal
	<-sigs
	server.Shutdown()
	log.Println("Server shutdown complete")
}