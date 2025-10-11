package main

import (
	"bytes"
	"context"
	"fmt"
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
	PixelFormat webcam.PixelFormat
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

// Global camera configurations - will be detected automatically
var CameraConfigs [2]CameraConfig

func init() {
	// Initialize with default values, will be updated during detection
	CameraConfigs = [2]CameraConfig{
		{
			Width:       1280,
			Height:      720,
			FPS:         30,
			PixelFormat: webcam.PixelFormat(1196444237), // MJPEG
		},
		{
			Width:       1280,
			Height:      720,
			FPS:         30,
			PixelFormat: webcam.PixelFormat(1196444237), // MJPEG
		},
	}
}

func detectUSBCameras() error {
	log.Println("Detecting USB cameras...")
	
	// Use v4l2-ctl to list devices with details
	cmd := exec.Command("v4l2-ctl", "--list-devices")
	output, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("failed to list devices: %v", err)
	}

	lines := strings.Split(string(output), "\n")
	var currentDevice string
	var currentPaths []string
	var usbCameras []CameraConfig

	for _, line := range lines {
		line = strings.TrimSpace(line)
		if line == "" {
			if currentDevice != "" && len(currentPaths) > 0 {
				// Check if this is a USB camera
				isUSBCamera := false
				for _, path := range currentPaths {
					// Get detailed info for this device
					infoCmd := exec.Command("v4l2-ctl", "--device", path, "--info")
					infoOutput, err := infoCmd.CombinedOutput()
					if err != nil {
						continue
					}
					
					info := string(infoOutput)
					if strings.Contains(info, "usb") {
						isUSBCamera = true
						
						// Extract USB info
						var vendorID, productID string
						lines := strings.Split(info, "\n")
						var busInfo string
						
						for _, infoLine := range lines {
							if strings.Contains(infoLine, "Bus info") {
								parts := strings.Split(infoLine, ":")
								if len(parts) > 1 {
									busInfo = strings.TrimSpace(parts[1])
								}
							}
						}
						
						// Try to get USB IDs from sysfs
						deviceName := strings.TrimPrefix(path, "/dev/")
						usbInfo := getUSBInfo(deviceName)
						if usbInfo != "" {
							ids := strings.Split(usbInfo, ":")
							if len(ids) == 2 {
								vendorID = ids[0]
								productID = ids[1]
							}
						}
						
						cameraConfig := CameraConfig{
							DevicePath:  path,
							DeviceID:    fmt.Sprintf("usb-camera-%d", len(usbCameras)),
							VendorID:    vendorID,
							ProductID:   productID,
							DeviceName:  currentDevice,
							Width:       1280,
							Height:      720,
							FPS:         30,
							PixelFormat: webcam.PixelFormat(1196444237), // MJPEG
						}
						
						usbCameras = append(usbCameras, cameraConfig)
						log.Printf("Found USB camera: %s at %s [USB: %s:%s]", 
							currentDevice, path, vendorID, productID)
						break
					}
				}
			}
			currentDevice = ""
			currentPaths = nil
		} else if !strings.HasPrefix(line, "\t") && !strings.HasPrefix(line, " ") {
			// This is a device name
			currentDevice = line
		} else if strings.HasPrefix(line, "\t") || strings.HasPrefix(line, " ") {
			// This is a device path
			path := strings.TrimSpace(line)
			if strings.HasPrefix(path, "/dev/video") {
				currentPaths = append(currentPaths, path)
			}
		}
	}

	if len(usbCameras) == 0 {
		return fmt.Errorf("no USB cameras detected")
	}

	// Assign detected USB cameras to our configs
	for i, camera := range usbCameras {
		if i >= 2 {
			break
		}
		CameraConfigs[i] = camera
	}

	log.Printf("Successfully detected %d USB cameras", len(usbCameras))
	return nil
}

func getUSBInfo(deviceName string) string {
	// Try to read USB vendor and product ID from sysfs
	vendorPath := fmt.Sprintf("/sys/class/video4linux/%s/device/../idVendor", deviceName)
	productPath := fmt.Sprintf("/sys/class/video4linux/%s/device/../idProduct", deviceName)
	
	vendorBytes, err := os.ReadFile(vendorPath)
	if err != nil {
		return ""
	}
	vendor := strings.TrimSpace(string(vendorBytes))
	
	productBytes, err := os.ReadFile(productPath)
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
	log.Printf("Initializing USB camera: %s (%s)", cs.config.DevicePath, cs.config.DeviceName)
	
	cam, err := webcam.Open(cs.config.DevicePath)
	if err != nil {
		log.Printf("Failed to open USB camera %s: %v", cs.config.DevicePath, err)
		return err
	}
	cs.cam = cam

	// Get supported formats
	formats := cs.cam.GetSupportedFormats()
	log.Printf("Supported formats for %s:", cs.config.DevicePath)
	for format, desc := range formats {
		log.Printf("  %s: %s", format, desc)
	}

	// Try to set format - fix parameter order
	formatDesc := cs.cam.GetSupportedFormats()
	var selectedFormat webcam.PixelFormat
	
	// Prefer MJPEG for hardware acceleration
	for fmt, desc := range formatDesc {
		if fmt == "MJPG" {
			selectedFormat = webcam.PixelFormat(1196444237) // MJPEG
			log.Printf("Selecting MJPEG format for hardware acceleration")
			break
		}
	}
	
	// If MJPEG not available, try YUYV
	if selectedFormat == 0 {
		for fmt, desc := range formatDesc {
			if fmt == "YUYV" {
				selectedFormat = webcam.PixelFormat(1448695129) // YUYV
				log.Printf("Selecting YUYV format (MJPEG not available)")
				break
			}
		}
	}
	
	if selectedFormat == 0 {
		// Use first available format
		for fmt := range formatDesc {
			selectedFormat = fmt
			log.Printf("Using available format: %s", fmt)
			break
		}
	}
	
	cs.config.PixelFormat = selectedFormat
	
	// Set format with correct parameter order: format, width, height
	_, _, _, err = cs.cam.SetImageFormat(selectedFormat, cs.config.Width, cs.config.Height)
	if err != nil {
		log.Printf("Failed to set image format: %v", err)
		cs.cam.Close()
		return err
	}

	// Set FPS - convert uint32 to float32
	err = cs.cam.SetFramerate(float32(cs.config.FPS))
	if err != nil {
		log.Printf("Warning: Could not set FPS to %d: %v", cs.config.FPS, err)
	}

	// Start streaming
	err = cs.cam.StartStreaming()
	if err != nil {
		cs.cam.Close()
		return err
	}

	cs.running = true
	cs.connected = true
	log.Printf("USB camera %s initialized successfully: %dx%d @ %d fps", 
		cs.config.DevicePath, cs.config.Width, cs.config.Height, cs.config.FPS)
	return nil
}

func (cs *CameraStream) StartCapture() {
	go func() {
		defer func() {
			if r := recover(); r != nil {
				log.Printf("USB camera %s capture panicked: %v", cs.config.DevicePath, r)
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
	// Check if frame is already JPEG (MJPEG format)
	if cs.config.PixelFormat == webcam.PixelFormat(1196444237) {
		return frame, nil
	}
	
	// Convert other formats to JPEG
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
	log.Printf("Reconnecting USB camera %s...", cs.config.DevicePath)
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
			log.Printf("USB camera %s reconnected successfully", cs.config.DevicePath)
			return
		}
		log.Printf("Reconnection attempt %d failed for %s: %v", i+1, cs.config.DevicePath, err)
		time.Sleep(2 * time.Second)
	}

	log.Printf("Failed to reconnect USB camera %s after 5 attempts", cs.config.DevicePath)
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
	// Detect USB cameras first
	err := detectUSBCameras()
	if err != nil {
		log.Fatalf("USB camera detection failed: %v", err)
	}

	server := &StreamingServer{}

	// Initialize detected USB cameras
	camerasInitialized := 0
	for i := 0; i < len(CameraConfigs) && i < 2; i++ {
		if CameraConfigs[i].DevicePath == "" {
			continue
		}

		stream := NewCameraStream(CameraConfigs[i])
		err := stream.Initialize()
		if err != nil {
			log.Printf("Failed to initialize USB camera %s: %v", CameraConfigs[i].DevicePath, err)
			continue
		}
		server.cameras[i] = stream
		stream.StartCapture()
		camerasInitialized++
		time.Sleep(500 * time.Millisecond) // Stagger initialization
	}

	if camerasInitialized == 0 {
		log.Fatal("No USB cameras could be initialized")
	}

	log.Printf("Successfully initialized %d USB cameras", camerasInitialized)
	return server
}

func (ss *StreamingServer) GenerateMJPEG(cameraID int) gin.HandlerFunc {
	return func(c *gin.Context) {
		if cameraID < 0 || cameraID >= len(ss.cameras) || ss.cameras[cameraID] == nil {
			http.Error(c.Writer, "USB camera not found", http.StatusNotFound)
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
	width, height := 640, 480
	img := image.NewRGBA(image.Rect(0, 0, width, height))
	
	// Fill with color based on connection status
	color := [3]uint8{80, 50, 50} // Reddish for disconnected
	if connected {
		color = [3]uint8{50, 50, 80} // Bluish for connected
	}
	
	for y := 0; y < height; y++ {
		for x := 0; x < width; x++ {
			offset := (y*img.Stride + x*4)
			img.Pix[offset] = color[0]     // R
			img.Pix[offset+1] = color[1]   // G  
			img.Pix[offset+2] = color[2]   // B
			img.Pix[offset+3] = 255        // A
		}
	}
	
	var buf bytes.Buffer
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
			"message": "USB Camera Streaming Server",
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
			c.JSON(404, gin.H{"error": "USB camera not found"})
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
			c.JSON(404, gin.H{"error": "USB camera not found"})
			return
		}

		camera := ss.cameras[cameraID]
		go camera.Reconnect()

		c.JSON(200, gin.H{
			"message":     "Reconnection initiated",
			"camera_id":   cameraID,
			"device_path": camera.config.DevicePath,
		})
	}
}

func (ss *StreamingServer) DiscoverCameras(c *gin.Context) {
	err := detectUSBCameras()
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
		"message": "USB camera discovery completed",
		"cameras": cameras,
	})
}

func (ss *StreamingServer) Start(addr string) error {
	router := ss.SetupRoutes()

	ss.httpServer = &http.Server{
		Addr:    addr,
		Handler: router,
	}

	log.Printf("Starting USB camera streaming server on %s", addr)
	return ss.httpServer.ListenAndServe()
}

func (ss *StreamingServer) Shutdown() {
	log.Println("Shutting down USB camera streaming server...")

	for i, camera := range ss.cameras {
		if camera != nil {
			log.Printf("Closing USB camera %d (%s)...", i, camera.config.DevicePath)
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

	log.Println("USB Camera Streaming Server started on :8080")
	log.Println("Endpoints:")
	log.Println("  GET /              - Server info")
	log.Println("  GET /camera/0      - Stream USB camera 0")
	log.Println("  GET /camera/1      - Stream USB camera 1") 
	log.Println("  GET /status/0      - USB camera 0 status")
	log.Println("  GET /status/1      - USB camera 1 status")
	log.Println("  GET /discover      - Rediscover USB cameras")

	// Wait for shutdown signal
	<-sigs
	server.Shutdown()
	log.Println("Server shutdown complete")
}