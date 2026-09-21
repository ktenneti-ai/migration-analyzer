#!/usr/bin/env bash
# Runs once when the Codespace is created: installs backend + frontend deps.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Setting up backend (Python venv)..."
python3 -m venv backend/.venv
backend/.venv/bin/pip install --upgrade pip -q
backend/.venv/bin/pip install -q -r backend/requirements.txt

echo "==> Setting up frontend (npm install)..."
npm install --prefix frontend

echo "==> Setup complete."
