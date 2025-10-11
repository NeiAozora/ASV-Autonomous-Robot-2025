from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from enum import Enum
import uvicorn
import time
from typing import Optional

app = FastAPI(title="Simple Robot Server", version="1.0.0")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple state
class RobotMode(str, Enum):
    AUTONOMOUS = "autonomous"
    REMOTE = "remote"

current_mode = RobotMode.AUTONOMOUS
connected_clients = {}

# Pydantic models
class ModeChangeRequest(BaseModel):
    mode: RobotMode
    client_id: str

class JoystickData(BaseModel):
    client_id: str
    data_type: str
    axis: Optional[int] = None
    value: Optional[float] = None
    button: Optional[int] = None
    pressed: Optional[bool] = None
    hat: Optional[int] = None
    hat_value: Optional[list] = None
    axis_name: Optional[str] = None
    button_name: Optional[str] = None

class PingRequest(BaseModel):
    client_id: str

class ConnectRequest(BaseModel):
    client_name: str

@app.get("/")
async def root():
    return {
        "message": "Simple Robot Server", 
        "status": "running",
        "current_mode": current_mode,
        "connected_clients": len(connected_clients)
    }

@app.get("/ping")
async def ping():
    return {"status": "ok", "timestamp": time.time()}

@app.post("/ping")
async def client_ping(request: PingRequest):
    """Update client last ping time"""
    connected_clients[request.client_id] = time.time()
    return {
        "status": "ok", 
        "timestamp": time.time(),
        "current_mode": current_mode
    }

@app.post("/connect")
async def connect_client(request: ConnectRequest):
    """Register a new client"""
    client_id = f"{request.client_name}_{int(time.time())}"
    connected_clients[client_id] = time.time()
    
    return {
        "status": "connected",
        "client_id": client_id,
        "current_mode": current_mode
    }

@app.get("/mode")
async def get_current_mode():
    """Get current robot mode"""
    return {"mode": current_mode}

@app.post("/mode")
async def change_mode(request: ModeChangeRequest):
    """Change robot mode"""
    global current_mode
    
    # Update mode
    old_mode = current_mode
    current_mode = request.mode
    
    print(f"Mode changed from {old_mode} to {current_mode} by client {request.client_id}")
    
    return {
        "status": "success",
        "previous_mode": old_mode,
        "new_mode": current_mode
    }

@app.post("/joystick")
async def receive_joystick_data(data: JoystickData):
    """Receive joystick data from client"""
    # Only accept joystick data in REMOTE mode
    if current_mode != RobotMode.REMOTE:
        raise HTTPException(
            status_code=403,
            detail="Joystick data only accepted in REMOTE mode"
        )
    
    # Print received data for debugging
    if data.data_type == "axis" and abs(data.value or 0) > 0.1:
        print(f"Joystick axis: {data.axis_name} = {data.value:.3f}")
    elif data.data_type == "button" and data.pressed:
        print(f"Joystick button: {data.button_name} PRESSED")
    elif data.data_type == "hat" and data.hat_value != [0, 0]:
        print(f"Joystick hat: {data.hat_value}")
    
    return {"status": "received", "data_type": data.data_type}

@app.get("/status")
async def get_server_status():
    """Get server status"""
    return {
        "current_mode": current_mode,
        "connected_clients": len(connected_clients)
    }

# Cleanup old clients periodically
import threading
def cleanup_clients():
    while True:
        current_time = time.time()
        expired_clients = [
            client_id for client_id, last_seen in connected_clients.items()
            if current_time - last_seen > 10  # 10 seconds timeout
        ]
        for client_id in expired_clients:
            del connected_clients[client_id]
            print(f"Cleaned up expired client: {client_id}")
        time.sleep(5)

cleanup_thread = threading.Thread(target=cleanup_clients, daemon=True)
cleanup_thread.start()

if __name__ == "__main__":
    print("Starting Simple Robot Server...")
    print("Server will run on http://localhost:2000")
    uvicorn.run(app, host="0.0.0.0", port=2000)