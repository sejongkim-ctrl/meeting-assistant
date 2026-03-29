#!/bin/bash
# meeting-assistant Phase 3 launcher
# Usage: ./start.sh [--dev]

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

# Load env
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

if [ "$1" = "--dev" ]; then
  echo "== DEV MODE: FastAPI + Vite dev server =="
  # Backend
  venv/bin/python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8001 &
  BACKEND_PID=$!
  echo "Backend PID: $BACKEND_PID"

  # Frontend dev server
  cd frontend && npm run dev &
  FRONTEND_PID=$!
  echo "Frontend PID: $FRONTEND_PID"

  echo ""
  echo "Backend:  http://localhost:8001/docs"
  echo "Frontend: http://localhost:5175"
  echo ""
  echo "Press Ctrl+C to stop both."

  trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
  wait
else
  echo "== PRODUCTION MODE: FastAPI serves frontend/dist =="
  # Build frontend if dist is missing or outdated
  if [ ! -d frontend/dist ] || [ frontend/src -nt frontend/dist ]; then
    echo "Building frontend..."
    cd frontend && npm run build && cd ..
  fi

  venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8001

  echo ""
  echo "App: http://localhost:8001/app"
fi
