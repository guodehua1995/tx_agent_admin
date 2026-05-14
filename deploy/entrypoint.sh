#!/bin/sh
set -e

echo "=== Starting Nginx ==="
nginx

echo "=== Starting FastAPI Backend ==="
python run.py
