#!/bin/bash

echo "Building Dual Camera Streamer with automatic device detection..."

# Install dependencies
sudo apt update
sudo apt install -y \
    libv4l-dev \
    libjpeg-dev \
    v4l-utils

# Fix go modules
echo "Downloading Go modules..."
go mod download
go mod tidy

# Check camera devices
echo "Available camera devices:"
v4l2-ctl --list-devices

echo "Camera details:"
for device in /dev/video*; do
    if [ -c "$device" ]; then
        echo "=== $device ==="
        v4l2-ctl --device $device --info 2>/dev/null | grep -E "(Card type|Bus info)" || echo "Cannot query device"
    fi
done

# Build the application
export CGO_ENABLED=1
export GOOS=linux
export GOARCH=arm64  # Change to amd64 for x86 systems

echo "Building application..."
go build -o dual-camera-streamer -ldflags="-s -w" main.go

if [ $? -eq 0 ]; then
    echo "Build successful!"
    echo "Run: ./dual-camera-streamer"
else
    echo "Build failed!"
    exit 1
fi