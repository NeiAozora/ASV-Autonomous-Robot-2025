import threading
import time
import cv2
import uvicorn
from fastapi import FastAPI, Response
from fastapi.responses import StreamingResponse
import numpy as np
from contextlib import asynccontextmanager
import asyncio

# Konfigurasi kamera - MINIMAL 720p
CAMERAS = [
    {"id": 0, "fps": 30, "width": 1280, "height": 720, "name": "Kamera 1"},
    {"id": 1, "fps": 30, "width": 1280, "height": 720, "name": "Kamera 2"}
]

# Global variables untuk performa tinggi
latest_frames = [None, None]
frame_locks = [threading.Lock(), threading.Lock()]
camera_threads = []

class HighPerformanceCamera(threading.Thread):
    def __init__(self, camera_id, fps, width, height):
        threading.Thread.__init__(self)
        self.camera_id = camera_id
        self.fps = fps
        self.width = width
        self.height = height
        self.running = True
        self.frame_count = 0
        self.last_time = time.time()
        
    def run(self):
        # Buka kamera dengan optimasi
        cap = cv2.VideoCapture(self.camera_id)
        
        # Set resolusi 720p
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)  # Buffer kecil untuk latency rendah
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))  # Hardware acceleration
        
        # Optimasi untuk performa
        cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)
        
        print(f"Kamera {self.camera_id} started: {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))} @ {cap.get(cv2.CAP_PROP_FPS)} FPS")
        
        while self.running:
            success, frame = cap.read()
            if success:
                # Maintain aspect ratio dan resize ke 720p
                if frame.shape[1] != self.width or frame.shape[0] != self.height:
                    frame = cv2.resize(frame, (self.width, self.height))
                
                # Optimasi encoding dengan quality balance
                encode_params = [cv2.IMWRITE_JPEG_QUALITY, 85, cv2.IMWRITE_JPEG_OPTIMIZE, 1]
                _, jpeg_frame = cv2.imencode('.jpg', frame, encode_params)
                
                with frame_locks[self.camera_id]:
                    latest_frames[self.camera_id] = jpeg_frame.tobytes()
                
                # FPS monitoring
                self.frame_count += 1
                current_time = time.time()
                if current_time - self.last_time >= 1.0:
                    actual_fps = self.frame_count / (current_time - self.last_time)
                    print(f"Kamera {self.camera_id}: {actual_fps:.1f} FPS")
                    self.frame_count = 0
                    self.last_time = current_time
            
            # Kontrol FPS yang presisi
            time.sleep(1.0 / self.fps)
        
        cap.release()
        print(f"Kamera {self.camera_id} stopped")

async def frame_generator(camera_id, fps):
    """Generator yang dioptimasi untuk streaming dengan kontrol FPS"""
    frame_interval = 1.0 / fps
    last_frame_time = time.time()
    
    while True:
        current_time = time.time()
        elapsed = current_time - last_frame_time
        
        if elapsed >= frame_interval:
            with frame_locks[camera_id]:
                frame_data = latest_frames[camera_id]
            
            if frame_data is not None:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n')
                last_frame_time = current_time
            else:
                # Kirim frame kosong jika tidak ada data
                blank_frame = generate_blank_frame()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + blank_frame + b'\r\n')
                last_frame_time = current_time
        
        # Yield control untuk async
        await asyncio.sleep(0.001)

def generate_blank_frame():
    """Generate blank frame sebagai fallback"""
    blank = np.zeros((720, 1280, 3), dtype=np.uint8)
    cv2.putText(blank, "Kamera Tidak Terhubung", (50, 360), 
                cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    _, jpeg = cv2.imencode('.jpg', blank, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return jpeg.tobytes()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Starting camera threads...")
    
    for camera in CAMERAS:
        thread = HighPerformanceCamera(
            camera_id=camera["id"],
            fps=camera["fps"],
            width=camera["width"],
            height=camera["height"]
        )
        thread.daemon = True
        thread.start()
        camera_threads.append(thread)
    
    print("Server ready! Access streams at:")
    print("http://localhost:8000/camera/0")
    print("http://localhost:8000/camera/1")
    
    yield  # App running
    
    # Shutdown
    print("Stopping camera threads...")
    for thread in camera_threads:
        thread.running = False
    
    for thread in camera_threads:
        thread.join(timeout=2.0)

app = FastAPI(title="HD Camera Streaming Server", lifespan=lifespan)

@app.get("/camera/{camera_id}")
async def video_stream(camera_id: int):
    """Endpoint streaming untuk kamera tertentu"""
    if camera_id not in [0, 1]:
        return {"error": "Camera tidak ditemukan. Gunakan 0 atau 1"}
    
    camera_config = CAMERAS[camera_id]
    
    return StreamingResponse(
        frame_generator(camera_id, camera_config["fps"]),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Frame-Rate": str(camera_config["fps"])
        }
    )

@app.get("/health")
async def health_check():
    """Endpoint untuk mengecek status kamera"""
    status = {}
    for i, camera in enumerate(CAMERAS):
        with frame_locks[i]:
            is_active = latest_frames[i] is not None
        status[f"camera_{i}"] = {
            "active": is_active,
            "resolution": f"{camera['width']}x{camera['height']}",
            "target_fps": camera["fps"]
        }
    return status

@app.get("/")
async def root():
    return {
        "message": "HD Camera Streaming Server",
        "resolusi": "1280x720 (720p)",
        "target_fps": 30,
        "endpoints": {
            "stream_kamera_0": "/camera/0",
            "stream_kamera_1": "/camera/1",
            "health_check": "/health"
        }
    }

if __name__ == "__main__":
    # Konfigurasi server high-performance
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        access_log=False,  # Nonaktifkan log untuk performa
        log_level="error",
        workers=1,  # Single worker untuk konsistensi frame
        loop="asyncio",  # Gunakan asyncio loop
        max_requests=0,  # No request limiting
        timeout_keep_alive=300  # Keep-alive panjang
    )