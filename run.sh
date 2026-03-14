#!/bin/bash
# run.sh - Startup script for Docker container
# Starts both the FastAPI backend and Streamlit frontend

# Start FastAPI in the background on port 8000
echo "Starting FastAPI backend..."
uvicorn api:app --host 0.0.0.0 --port 8000 --workers 1 --timeout-keep-alive 300 &
API_PID=$!

# Wait for API to be ready
echo "Waiting for API to initialize..."
sleep 3

# Start Streamlit in the foreground on the port provided by Cloud Run (or default 8080)
echo "Starting Streamlit frontend..."
export API_URL="http://localhost:8000"
streamlit run streamlit_app.py \
    --server.port ${PORT:-8080} \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false

# Wait for background processes to finish (prevents container from exiting)
wait $API_PID
