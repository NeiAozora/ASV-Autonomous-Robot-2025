#!/bin/bash

# Get camera list and run server
CAMERA_JSON=$(./../get_camera.sh | tail -n 1)
echo "Using cameras: $CAMERA_JSON"
./dual-camera-streamer "$CAMERA_JSON"