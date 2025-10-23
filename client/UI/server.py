# server.py
from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import random, datetime

app = FastAPI(title="Dummy Telemetry API")

# Karena client kemungkinan dibuka dari file:// atau localhost, izinkan semua origin untuk pengujian lokal
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class RestartPayload(BaseModel):
    mode: str | None = None

def random_coord():
    return f"{random.uniform(-90,90):.6f}"

def current_time_local_str():
    return datetime.datetime.now().strftime("%H:%M:%S")

@app.get("/api/dashboard")
def api_dashboard():
    """Kembalikan JSON yang memuat semua field yang client harapkan."""
    sog_knots = round(random.uniform(0, 20), 1)
    cog_knots = round(random.uniform(0, 360), 1)
    heading = random.randint(0, 359)
    trajectory_mode = random.choice(["A", "B"])
    current_state = random.choice(["Belum Mulai", "Start", "Perjalanan", "Finish"])

    log_time = current_time_local_str().replace(":", "_")
    log_kamera_atas = f"TipeLintasan_Atas_Hijau_{log_time}.jpg"
    log_kamera_bawah = random.choice([f"TipeLintasan_Bawah_Hijau_{log_time}.jpg", "Menuggu...."])

    return {
        "gps_latitude": random_coord(),
        "gps_longitude": random_coord(),
        "battery_level": f"{random.uniform(20,100):.1f}",
        "voltage": f"{random.uniform(3.0,6.0):.1f}",
        "current": f"{random.uniform(0.05,0.7):.5f}",
        "sog_knots": f"{sog_knots:.1f}",
        "sog_kmh": f"{(sog_knots * 1.852):.1f}",
        "cog_knots": f"{cog_knots:.1f}",
        "cog_kmh": f"{(cog_knots * 1.852):.1f}",
        "heading": heading,
        "log_kamera_atas": log_kamera_atas,
        "log_kamera_bawah": log_kamera_bawah,
        "trajectory_mode": trajectory_mode,
        "current_state": current_state,
        # metadata
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    }

@app.get("/api/photos")
def api_photos():
    """Kembalikan daftar foto dummy untuk page 'Daftar Foto'."""
    base_date = datetime.date(2025, 1, 15)
    photos = []
    for i in range(1, 8):
        photos.append({
            "name": f"TipeLintasan_{i}_Time.jpg",
            "time": f"{13 + (i//2)}:{(15 * i) % 60:02d}",
            "date": base_date.strftime("%d %B %Y"),
            "download_url": f"https://example.com/download/TipeLintasan_{i}_Time.jpg"
        })
    return {"photos": photos}

@app.get("/api/video_urls")
def api_video_urls():
    """Kembalikan URL video streaming/preview (dummy)."""
    # Contoh video publik — di aplikasi nyata ganti dengan URL streaming RTSP/HTTP Anda
    demo = "https://assets.mixkit.co/videos/preview/mixkit-aerial-view-of-a-sailboat-in-the-sea-34560-large.mp4"
    return {
        "live_foto_bawah": demo,
        "live_kamera_bawah": demo
    }

@app.post("/api/restart")
def api_restart(payload: RestartPayload = Body(...)):
    """Terima permintaan restart dari client; kembalikan hasil (dummy)."""
    mode = payload.mode or "unknown"
    # Di sistem nyata: trigger reset state, clear sessions, dsb.
    return {
        "status": "ok",
        "message": f"Restart requested for mode {mode}",
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z"
    }

@app.get("/api/ping")
def api_ping():
    """
    Health/ping endpoint ringan.
    Mengembalikan 200 OK dengan JSON singkat.
    """
    return {
        "status": "ok",
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)