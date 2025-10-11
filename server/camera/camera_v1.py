import threading
import time
import cv2
import uvicorn
from fastapi import FastAPI, Response, HTTPException
from fastapi.responses import StreamingResponse
import numpy as np
import logging
from typing import Optional

# Konfigurasi logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Dual Camera Streaming Server")

# Konfigurasi kamera - 720p minimal
CAMERAS = [
    {"id": 0, "fps": 30, "width": 1280, "height": 720, "name": "Kamera Utama"},
    {"id": 1, "fps": 30, "width": 1280, "height": 720, "name": "Kamera Sekunder"}
]

# Global variables
latest_frames = [None, None]
frame_locks = [threading.Lock(), threading.Lock()]
camera_threads = [None, None]
camera_status = [{"connected": False, "error_count": 0}, {"connected": False, "error_count": 0}]
status_locks = [threading.Lock(), threading.Lock()]

class CameraThread(threading.Thread):
    def __init__(self, camera_id, fps, width, height):
        threading.Thread.__init__(self)
        self.camera_id = camera_id
        self.fps = fps
        self.width = width
        self.height = height
        self.running = True
        self.cap = None
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.reconnect_delay = 2  # detik
        
    def initialize_camera(self):
        """Initialize camera dengan optimasi"""
        try:
            if self.cap is not None:
                self.cap.release()
                
            self.cap = cv2.VideoCapture(self.camera_id)
            if not self.cap.isOpened():
                logger.error(f"Camera {self.camera_id} gagal dibuka")
                return False
            
            # Set properti kamera untuk performa
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self.cap.set(cv2.CAP_PROP_FPS, self.fps)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)  # Buffer kecil
            
            # Coba set codec untuk performa lebih baik
            try:
                self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            except:
                logger.warning(f"MJPG codec tidak didukung di camera {self.camera_id}")
                
            # Test capture
            for _ in range(5):  # Coba beberapa kali
                success, frame = self.cap.read()
                if success and frame is not None:
                    with status_locks[self.camera_id]:
                        camera_status[self.camera_id]["connected"] = True
                        camera_status[self.camera_id]["error_count"] = 0
                    self.reconnect_attempts = 0
                    logger.info(f"Camera {self.camera_id} berhasil diinisialisasi")
                    return True
                time.sleep(0.1)
                
            logger.error(f"Camera {self.camera_id} test capture gagal")
            return False
            
        except Exception as e:
            logger.error(f"Error initialize camera {self.camera_id}: {str(e)}")
            return False
    
    def reconnect_camera(self):
        """Coba reconnect ke kamera"""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error(f"Camera {self.camera_id} mencapai batas maksimal reconnect attempts")
            return False
            
        self.reconnect_attempts += 1
        logger.info(f"Attempting reconnect camera {self.camera_id} ({self.reconnect_attempts}/{self.max_reconnect_attempts})")
        
        time.sleep(self.reconnect_delay)
        return self.initialize_camera()
    
    def run(self):
        logger.info(f"Starting camera thread {self.camera_id}")
        
        # Initial camera setup
        if not self.initialize_camera():
            logger.error(f"Gagal inisialisasi camera {self.camera_id} pada startup")
            return
        
        frame_interval = 1.0 / self.fps
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        while self.running:
            try:
                start_time = time.time()
                
                # Capture frame
                success, frame = self.cap.read()
                
                if not success or frame is None:
                    consecutive_errors += 1
                    logger.warning(f"Camera {self.camera_id} frame capture gagal ({consecutive_errors}/{max_consecutive_errors})")
                    
                    if consecutive_errors >= max_consecutive_errors:
                        with status_locks[self.camera_id]:
                            camera_status[self.camera_id]["connected"] = False
                            camera_status[self.camera_id]["error_count"] += 1
                        
                        if not self.reconnect_camera():
                            logger.error(f"Camera {self.camera_id} disconnect permanen")
                            break
                        consecutive_errors = 0
                    
                    continue
                
                # Reset error counter jika berhasil
                consecutive_errors = 0
                
                # Resize frame ke 720p jika diperlukan
                if frame.shape[1] != self.width or frame.shape[0] != self.height:
                    frame = cv2.resize(frame, (self.width, self.height))
                
                # Encode frame ke JPEG dengan kualitas optimal
                encode_params = [cv2.IMWRITE_JPEG_QUALITY, 85]  # Balance kualitas & performa
                success, jpeg = cv2.imencode('.jpg', frame, encode_params)
                
                if success:
                    with frame_locks[self.camera_id]:
                        latest_frames[self.camera_id] = jpeg.tobytes()
                
                # Maintain FPS
                processing_time = time.time() - start_time
                sleep_time = max(0, frame_interval - processing_time)
                time.sleep(sleep_time)
                
            except Exception as e:
                logger.error(f"Error dalam camera thread {self.camera_id}: {str(e)}")
                time.sleep(1)  # Prevent tight loop on error
        
        # Cleanup
        if self.cap is not None:
            self.cap.release()
        with status_locks[self.camera_id]:
            camera_status[self.camera_id]["connected"] = False
        logger.info(f"Camera thread {self.camera_id} stopped")

def generate_frames(camera_id):
    """Generator untuk streaming response"""
    last_frame_time = time.time()
    timeout = 5  # Timeout jika tidak ada frame baru
    
    while True:
        try:
            # Check camera status
            with status_locks[camera_id]:
                if not camera_status[camera_id]["connected"]:
                    # Kirim placeholder image jika kamera disconnect
                    placeholder = generate_placeholder_image(camera_id)
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + placeholder + b'\r\n\r\n')
                    time.sleep(1)
                    continue
            
            # Get latest frame
            with frame_locks[camera_id]:
                frame_data = latest_frames[camera_id]
            
            if frame_data is not None:
                last_frame_time = time.time()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n\r\n')
            else:
                # Timeout check
                if time.time() - last_frame_time > timeout:
                    logger.warning(f"Stream timeout untuk camera {camera_id}")
                    break
            
            # Maintain FPS untuk streaming
            time.sleep(1 / CAMERAS[camera_id]["fps"])
            
        except Exception as e:
            logger.error(f"Error dalam stream generator camera {camera_id}: {str(e)}")
            break

def generate_placeholder_image(camera_id):
    """Generate placeholder image ketika kamera disconnect"""
    img = np.zeros((720, 1280, 3), dtype=np.uint8)
    text = f"Camera {camera_id} - Disconnected"
    font = cv2.FONT_HERSHEY_SIMPLEX
    text_size = cv2.getTextSize(text, font, 1, 2)[0]
    text_x = (1280 - text_size[0]) // 2
    text_y = (720 + text_size[1]) // 2
    cv2.putText(img, text, (text_x, text_y), font, 1, (255, 255, 255), 2)
    _, jpeg = cv2.imencode('.jpg', img)
    return jpeg.tobytes()

@app.on_event("startup")
async def startup_event():
    """Start camera threads pada startup"""
    logger.info("Starting camera streaming server...")
    
    for i, camera in enumerate(CAMERAS):
        thread = CameraThread(
            camera_id=camera["id"],
            fps=camera["fps"],
            width=camera["width"],
            height=camera["height"]
        )
        thread.daemon = True
        thread.start()
        camera_threads[i] = thread
        time.sleep(1)  # Delay antara inisialisasi kamera

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup pada shutdown"""
    logger.info("Shutting down camera streaming server...")
    for thread in camera_threads:
        if thread is not None:
            thread.running = False

@app.get("/camera/{camera_id}")
async def video_feed(camera_id: int):
    """Endpoint streaming untuk kamera tertentu"""
    if camera_id not in [0, 1]:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    return StreamingResponse(
        generate_frames(camera_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Camera-Status": "connected" if camera_status[camera_id]["connected"] else "disconnected"
        }
    )

@app.get("/camera/{camera_id}/status")
async def camera_status_endpoint(camera_id: int):
    """Endpoint untuk mengecek status kamera"""
    if camera_id not in [0, 1]:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    with status_locks[camera_id]:
        return {
            "camera_id": camera_id,
            "connected": camera_status[camera_id]["connected"],
            "error_count": camera_status[camera_id]["error_count"],
            "config": CAMERAS[camera_id]
        }

@app.post("/camera/{camera_id}/reconnect")
async def reconnect_camera(camera_id: int):
    """Force reconnect ke kamera"""
    if camera_id not in [0, 1]:
        raise HTTPException(status_code=404, detail="Camera not found")
    
    thread = camera_threads[camera_id]
    if thread and hasattr(thread, 'reconnect_camera'):
        success = thread.reconnect_camera()
        return {"camera_id": camera_id, "reconnect_success": success}
    
    return {"camera_id": camera_id, "reconnect_success": False}

@app.get("/")
async def root():
    """Root endpoint dengan info server"""
    status_info = []
    for i in range(2):
        with status_locks[i]:
            status_info.append({
                "camera_id": i,
                "connected": camera_status[i]["connected"],
                "config": CAMERAS[i]
            })
    
    return {
        "message": "Dual Camera Streaming Server", 
        "status": "running",
        "cameras": status_info
    }

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        access_log=True,
        workers=1  # Single worker karena menggunakan thread sharing
    )