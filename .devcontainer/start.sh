#!/usr/bin/env bash
# Runs every time the Codespace (re)starts: launches both dev servers in the
# background so the forwarded ports are live as soon as the Codespace is ready.
cd "$(dirname "$0")/.."

export NVM_DIR="${NVM_DIR:-/usr/local/share/nvm}"
if [ -s "$NVM_DIR/nvm.sh" ]; then
  # shellcheck disable=SC1091
  source "$NVM_DIR/nvm.sh"
fi

LOG_DIR="/tmp/migration-analyzer-logs"
mkdir -p "$LOG_DIR"

is_listening() { (echo > "/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

# postStartCommand can run more than once per Codespace session (e.g. once
# when the container starts, again when a client attaches) — without this
# lock, a second invocation's pkill below can kill the dev server the first
# invocation just launched moments earlier. That failure is silent: the
# process is killed, not crashed, so nothing gets appended to its log —
# the public port just mysteriously stops responding with no clue why.
exec 9>"$LOG_DIR/start.lock"
if ! flock -n 9; then
  echo "==> Another start.sh is already running — skipping this invocation." >> "$LOG_DIR/start.log"
  exit 0
fi

if is_listening 8000 && is_listening 5180; then
  echo "==> Both servers already up — nothing to do." > "$LOG_DIR/start.log"
  exit 0
fi

echo "==> node: $(command -v node || echo NOT FOUND) ($(node --version 2>&1))" > "$LOG_DIR/frontend.log"
echo "==> npm:  $(command -v npm || echo NOT FOUND) ($(npm --version 2>&1))" >> "$LOG_DIR/frontend.log"

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

# Verify each server is actually accepting connections before declaring
# success — a silent failure here previously showed up only as a forwarded
# port that mysteriously 401s, with nothing in either log explaining why.
{
  for port in 8000 5180; do
    ok=0
    for _ in $(seq 1 20); do
      if is_listening "$port"; then
        ok=1
        break
      fi
      sleep 1
    done
    if [ "$ok" = 1 ]; then
      echo "==> Port $port is listening."
    else
      echo "==> WARNING: port $port is NOT listening after 20s."
    fi
  done
} > "$LOG_DIR/start.log" 2>&1

echo "==> Backend log:  $LOG_DIR/backend.log"
echo "==> Frontend log: $LOG_DIR/frontend.log"
echo "==> Startup summary: $LOG_DIR/start.log"
