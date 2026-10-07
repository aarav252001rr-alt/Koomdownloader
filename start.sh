#!/bin/bash
node /opt/bgutil/server/build/main.js --port 4416 &
sleep 2
uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}
