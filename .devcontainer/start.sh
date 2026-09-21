#!/usr/bin/env bash
# Runs every time the Codespace (re)starts: launches both dev servers in the
# background so the forwarded ports are live as soon as the Codespace is ready.
cd "$(dirname "$0")/.."

LOG_DIR="/tmp/migration-analyzer-logs"
mkdir -p "$LOG_DIR"

# Kill any servers left over from a previous start (e.g. container restart).
pkill -f "uvicorn app.main:app" 2>/dev/null || true
pkill -f "vite --host" 2>/dev/null || true
pkill -f "node .*vite" 2>/dev/null || true

echo "==> Starting backend on :8000..."
(cd backend && nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload \
  > "$LOG_DIR/backend.log" 2>&1 &)

echo "==> Starting frontend on :5180..."
(cd frontend && nohup npm run dev -- --host 0.0.0.0 \
  > "$LOG_DIR/frontend.log" 2>&1 &)

sleep 2
echo "==> Backend log:  $LOG_DIR/backend.log"
echo "==> Frontend log: $LOG_DIR/frontend.log"
echo "==> Open the forwarded 'Migration Analyzer' port (5180) to use the app."
