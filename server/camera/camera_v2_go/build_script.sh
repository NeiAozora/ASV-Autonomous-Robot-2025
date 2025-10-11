#!/bin/bash

# Build script for Linux with hardware acceleration support

echo "Building Dual Camera Streamer with hardware acceleration..."

# Install dependencies
sudo apt update
sudo apt install -y \
    libv4l-dev \
    libjpeg-dev \
    libva-dev \
    libva-drm2 \
    libva-x11-2 \
    vainfo \
    v4l-utils

# Check VAAPI hardware acceleration
echo "Checking hardware acceleration support..."
vainfo

# Check camera devices
echo "Available camera devices:"
ls -la /dev/video*

# Build the application
export CGO_ENABLED=1
export GOOS=linux
export GOARCH=amd64

go build -o dual-camera-streamer -ldflags="-s -w" main.go

echo "Build complete!"
echo "Run: ./dual-camera-streamer"