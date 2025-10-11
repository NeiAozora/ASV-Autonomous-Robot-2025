package main

import (
	"bytes"
	"context"
	"image"
	"image/jpeg"
	"log"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/blackjack/webcam"
	"golang.org/x/sys/unix"
)

type CameraConfig struct {
	DevicePath  string
	DeviceID    string
	VendorID    string
	ProductID   string
	DeviceName  string
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
	connected   bool
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

// Global camera configurations - will be detected automatically
var CameraConfigs [2]CameraConfig

func init() {
	// Initialize with default values, will be updated during detection
	CameraConfigs = [2]CameraConfig{
		{
			Width:       1280,
			Height:      720,
			FPS:         30,
			PixelFormat: V4L2_PIX_FMT_MJPEG,
		},
		{
			Width:       1280,
			Height:      720,
			FPS:         30,
			PixelFormat: V4L2_PIX_FMT_MJPEG,
		},
	}
}

func detectCameras() error {
	log.Println("Detecting available cameras...")
	
	// Method 1: Check /dev/video* devices
	videoDevices, err := os.ReadDir("/dev")
	if err != nil {
		return err
	}

	var videoPaths []string
	for _, entry := range videoDevices {
		if strings.HasPrefix(entry.Name(), "video") {
			videoPaths = append(videoPaths, "/dev/"+entry.Name())
		}
	}

	if len(videoPaths) == 0 {
		return fmt.Errorf("no video devices found in /dev")
	}

	log.Printf("Found video devices: %v", videoPaths)

	// Method 2: Use v4l2-ctl to get detailed info
	camerasFound := 0
	for _, device := range videoPaths {
		if camerasFound >= 2 {
			break
		}

		// Try to get camera info using v4l2-ctl
		cmd := exec.Command("v4l2-ctl", "--device", device, "--info")
		output, err := cmd.CombinedOutput()
		if err != nil {
			log.Printf("Cannot query device %s: %v", device, err)
			continue
		}

		info := string(output)
		lines := strings.Split(info, "\n")
		
		var cameraName, busInfo string
		for _, line := range lines {
			if strings.Contains(line, "Card type") {
				cameraName = strings.TrimSpace(strings.Split(line, ":")[1])
			}
			if strings.Contains(line, "Bus info") {
				busInfo = strings.TrimSpace(strings.Split(line, ":")[1])
			}
		}

		// Get USB info if available
		var vendorID, productID string
		if strings.Contains(busInfo, "usb") {
			// Extract from bus info like "usb-70090000.xusb-2.4.3"
			parts := strings.Split(busInfo, "-")
			if len(parts) >= 4 {
				// Try to get USB vendor:product from sysfs
				usbInfo := getUSBInfo(device)
				if usbInfo != "" {
					ids := strings.Split(usbInfo, ":")
					if len(ids) == 2 {
						vendorID = ids[0]
						productID = ids[1]
					}
				}
			}
		}

		log.Printf("Detected camera: %s (%s) at %s [USB: %s:%s]", 
			cameraName, busInfo, device, vendorID, productID)

		// Assign to our camera configs
		CameraConfigs[camerasFound] = CameraConfig{
			DevicePath:  device,
			DeviceID:    fmt.Sprintf("camera%d", camerasFound),
			VendorID:    vendorID,
			ProductID:   productID,
			DeviceName:  cameraName,
			Width:       1280,
			Height:      720,
			FPS:         30,
			PixelFormat: V4L2_PIX_FMT_MJPEG,
		}

		camerasFound++
	}

	if camerasFound == 0 {
		return fmt.Errorf("no usable cameras detected")
	}

	log.Printf("Successfully detected %d cameras", camerasFound)
	return nil
}

func getUSBInfo(devicePath string) string {
	// Extract USB vendor and product ID from sysfs
	// This is a simplified version - you might need to adjust based on your system
	basePath := "/sys/class/video4linux/"
	deviceName := strings.TrimPrefix(devicePath, "/dev/")
	
	usbPath := basePath + deviceName + "/device/../idVendor"
	vendorBytes, err := os.ReadFile(usbPath)
	if err != nil {
		return ""
	}
	vendor := strings.TrimSpace(string(vendorBytes))

	usbPath = basePath + deviceName + "/device/../idProduct"
	productBytes, err := os.ReadFile(usbPath)
	if err != nil {
		return ""
	}
	product := strings.TrimSpace(string(productBytes))

	return vendor + ":" + product
}

func NewCameraStream(config CameraConfig) *CameraStream {
	return &CameraStream{
		config:      config,
		frameBuffer: make(chan []byte, 10),
		running:     false,
		errorCount:  0,
		connected:   false,
	}
}

func (cs *CameraStream) Initialize() error {
	log.Printf("Initializing camera: %s (%s)", cs.config.DevicePath, cs.config.DeviceName)
	
	cam, err := webcam.Open(cs.config.DevicePath)
	if err != nil {
		log.Printf("Failed to open camera %s: %v", cs.config.DevicePath, err)
		return err
	}
	cs.cam = cam

	// Get supported formats
	formats := cs.cam.GetSupportedFormats()
	log.Printf("Supported formats for %s:", cs.config.DevicePath)
	for format, desc := range formats {
		log.Printf("  %s: %s", format, desc)
	}

	// Try MJPEG first, then YUYV as fallback
	_, _, _, err = cs.cam.SetImageFormat(cs.config.Width, cs.config.Height, webcam.PixelFormat(cs.config.PixelFormat))
	if err != nil {
		log.Printf("MJPEG not supported, trying YUYV: %v", err)
		_, _, _, err = cs.cam.SetImageFormat(cs.config.Width, cs.config.Height, webcam.PixelFormat(V4L2_PIX_FMT_YUYV))
		if err != nil {
			cam.Close()
			return fmt.Errorf("failed to set any supported format: %v", err)
		}
		// Update config to reflect actual format
		cs.config.PixelFormat = V4L2_PIX_FMT_YUYV
	}

	// Set FPS
	err = cs.cam.SetFramerate(cs.config.FPS)
	if err != nil {
		log.Printf("Warning: Could not set FPS to %d: %v", cs.config.FPS, err)
	}

	// Start streaming
	err = cs.cam.StartStreaming()
	if err != nil {
		cam.Close()
		return err
	}

	cs.running = true
	cs.connected = true
	log.Printf("Camera %s initialized successfully: %dx%d @ %d fps, format: 0x%x", 
		cs.config.DevicePath, cs.config.Width, cs.config.Height, cs.config.FPS, cs.config.PixelFormat)
	return nil
}

func (cs *CameraStream) StartCapture() {
	go func() {
		defer func() {
			if r := recover(); r != nil {
				log.Printf("Camera %s capture panicked: %v", cs.config.DevicePath, r)
				cs.Reconnect()
			}
		}()

		frameInterval := time.Second / time.Duration(cs.config.FPS)
		
		for cs.running {
			startTime := time.Now()
			
			err := cs.cam.WaitForFrame(5)
			switch err {
			case nil:
				frame, err := cs.cam.ReadFrame()
				if err != nil {
					log.Printf("Error reading frame from %s: %v", cs.config.DevicePath, err)
					cs.errorCount++
					if cs.errorCount > 10 {
						cs.Reconnect()
					}
					continue
				}

				if len(frame) == 0 {
					continue
				}

				processedFrame, err := cs.ProcessFrame(frame)
				if err != nil {
					log.Printf("Error processing frame from %s: %v", cs.config.DevicePath, err)
					continue
				}

				cs.mutex.Lock()
				cs.lastFrame = processedFrame
				cs.errorCount = 0
				cs.connected = true
				cs.mutex.Unlock()

				// Non-blocking send to buffer
				select {
				case cs.frameBuffer <- processedFrame:
				default:
					// Drop frame if buffer full
				}

			case unix.EAGAIN:
				// Timeout, continue
				continue
			default:
				log.Printf("Error waiting for frame from %s: %v", cs.config.DevicePath, err)
				cs.errorCount++
				cs.connected = false
				if cs.errorCount > 5 {
					cs.Reconnect()
				}
			}

			// Maintain FPS
			elapsed := time.Since(startTime)
			sleepTime := frameInterval - elapsed
			if sleepTime > 0 {
				time.Sleep(sleepTime)
			}
		}
	}()
}

func (cs *CameraStream) ProcessFrame(frame []byte) ([]byte, error) {
	if cs.config.PixelFormat == V4L2_PIX_FMT_MJPEG {
		return frame, nil
	}
	return cs.YUYVToJPEG(frame)
}

func (cs *CameraStream) YUYVToJPEG(data []byte) ([]byte, error) {
	width := int(cs.config.Width)
	height := int(cs.config.Height)

	img := image.NewYCbCr(image.Rect(0, 0, width, height), image.YCbCrSubsampleRatio422)

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

func (cs *CameraStream) IsConnected() bool {
	cs.mutex.RLock()
	defer cs.mutex.RUnlock()
	return cs.connected
}

func (cs *CameraStream) Reconnect() {
	log.Printf("Reconnecting camera %s...", cs.config.DevicePath)
	cs.mutex.Lock()
	cs.running = false
	cs.connected = false
	cs.mutex.Unlock()

	if cs.cam != nil {
		cs.cam.StopStreaming()
		cs.cam.Close()
	}

	time.Sleep(2 * time.Second)

	for i := 0; i < 5; i++ {
		err := cs.Initialize()
		if err == nil {
			cs.StartCapture()
			log.Printf("Camera %s reconnected successfully", cs.config.DevicePath)
			return
		}
		log.Printf("Reconnection attempt %d failed for %s: %v", i+1, cs.config.DevicePath, err)
		time.Sleep(2 * time.Second)
	}

	log.Printf("Failed to reconnect camera %s after 5 attempts", cs.config.DevicePath)
}

func (cs *CameraStream) Close() {
	cs.mutex.Lock()
	defer cs.mutex.Unlock()
	cs.running = false
	cs.connected = false
	if cs.cam != nil {
		cs.cam.StopStreaming()
		cs.cam.Close()
	}
	close(cs.frameBuffer)
}

func NewStreamingServer() *StreamingServer {
	// Detect cameras first
	err := detectCameras()
	if err != nil {
		log.Fatalf("Camera detection failed: %v", err)
	}

	server := &StreamingServer{}

	// Initialize detected cameras
	for i := 0; i < len(CameraConfigs) && i < 2; i++ {
		if CameraConfigs[i].DevicePath == "" {
			continue
		}

		stream := NewCameraStream(CameraConfigs[i])
		err := stream.Initialize()
		if err != nil {
			log.Printf("Failed to initialize camera %s: %v", CameraConfigs[i].DevicePath, err)
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
		c.Writer.Header().Set("X-Accel-Buffering", "no")

		flusher, ok := c.Writer.(http.Flusher)
		if !ok {
			http.Error(c.Writer, "Streaming not supported", http.StatusInternalServerError)
			return
		}

		camera := ss.cameras[cameraID]
		frameInterval := time.Second / time.Duration(camera.config.FPS)
		ticker := time.NewTicker(frameInterval)
		defer ticker.Stop()

		for {
			select {
			case <-c.Request.Context().Done():
				return
			case <-ticker.C:
				frame := camera.GetFrame()
				if frame == nil {
					// Send placeholder if no frame
					frame = generatePlaceholder(cameraID, camera.IsConnected())
				}

				_, err := c.Writer.Write([]byte("--frame\r\nContent-Type: image/jpeg\r\n\r\n"))
				if err != nil {
					return
				}

				_, err = c.Writer.Write(frame)
				if err != nil {
					return
				}

				_, err = c.Writer.Write([]byte("\r\n\r\n"))
				if err != nil {
					return
				}
				flusher.Flush()
			}
		}
	}
}

func generatePlaceholder(cameraID int, connected bool) []byte {
	img := image.NewRGBA(image.Rect(0, 0, 640, 480))
	
	// Create a simple placeholder image
	// In practice, you might want to use a proper image
	var buf bytes.Buffer
	var text string
	if connected {
		text = fmt.Sprintf("Camera %d - No Frame", cameraID)
	} else {
		text = fmt.Sprintf("Camera %d - Disconnected", cameraID)
	}
	
	// Simple colored placeholder
	for y := 0; y < 480; y++ {
		for x := 0; x < 640; x++ {
			offset := (y*640 + x) * 4
			if connected {
				img.Pix[offset] = 50   // R
				img.Pix[offset+1] = 50 // G  
				img.Pix[offset+2] = 80 // B
			} else {
				img.Pix[offset] = 80   // R
				img.Pix[offset+1] = 50 // G
				img.Pix[offset+2] = 50 // B
			}
			img.Pix[offset+3] = 255 // A
		}
	}
	
	jpeg.Encode(&buf, img, &jpeg.Options{Quality: 50})
	return buf.Bytes()
}

func (ss *StreamingServer) SetupRoutes() *gin.Engine {
	if os.Getenv("GIN_MODE") == "release" {
		gin.SetMode(gin.ReleaseMode)
	}

	router := gin.New()
	router.Use(gin.Recovery())

	// Root endpoint with camera info
	router.GET("/", func(c *gin.Context) {
		cameraInfo := make([]gin.H, 0)
		for i, cam := range ss.cameras {
			if cam != nil {
				cameraInfo = append(cameraInfo, gin.H{
					"camera_id":   i,
					"device_path": cam.config.DevicePath,
					"device_name": cam.config.DeviceName,
					"vendor_id":   cam.config.VendorID,
					"product_id":  cam.config.ProductID,
					"connected":   cam.IsConnected(),
					"resolution": gin.H{
						"width":  cam.config.Width,
						"height": cam.config.Height,
					},
					"fps": cam.config.FPS,
				})
			}
		}

		c.JSON(200, gin.H{
			"message": "Dual Camera Streaming Server",
			"cameras": cameraInfo,
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

	// Camera discovery endpoint
	router.GET("/discover", ss.DiscoverCameras)

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
			"camera_id":   cameraID,
			"device_path": camera.config.DevicePath,
			"device_name": camera.config.DeviceName,
			"vendor_id":   camera.config.VendorID,
			"product_id":  camera.config.ProductID,
			"connected":   camera.IsConnected(),
			"errors":      camera.errorCount,
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
			"message":    "Reconnection initiated",
			"camera_id":  cameraID,
			"device_path": camera.config.DevicePath,
		})
	}
}

func (ss *StreamingServer) DiscoverCameras(c *gin.Context) {
	err := detectCameras()
	if err != nil {
		c.JSON(500, gin.H{"error": err.Error()})
		return
	}

	cameras := make([]gin.H, 0)
	for i, config := range CameraConfigs {
		if config.DevicePath != "" {
			cameras = append(cameras, gin.H{
				"camera_id":   i,
				"device_path": config.DevicePath,
				"device_name": config.DeviceName,
				"vendor_id":   config.VendorID,
				"product_id":  config.ProductID,
				"resolution": gin.H{
					"width":  config.Width,
					"height": config.Height,
				},
				"fps": config.FPS,
			})
		}
	}

	c.JSON(200, gin.H{
		"message": "Camera discovery completed",
		"cameras": cameras,
	})
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
			log.Printf("Closing camera %d (%s)...", i, camera.config.DevicePath)
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

	log.Println("Server started on :8080")
	log.Println("Endpoints:")
	log.Println("  GET /              - Server info")
	log.Println("  GET /camera/0      - Stream camera 0")
	log.Println("  GET /camera/1      - Stream camera 1") 
	log.Println("  GET /status/0      - Camera 0 status")
	log.Println("  GET /status/1      - Camera 1 status")
	log.Println("  GET /discover      - Rediscover cameras")

	// Wait for shutdown signal
	<-sigs
	server.Shutdown()
	log.Println("Server shutdown complete")
}