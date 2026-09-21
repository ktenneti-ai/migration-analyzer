#!/usr/bin/env bash
# Runs once when the Codespace is created: installs backend + frontend deps.
set -euo pipefail
cd "$(dirname "$0")/.."

# The Node devcontainer feature installs Node via nvm, which registers
# itself in ~/.bashrc — but postCreateCommand runs as a non-interactive
# shell that doesn't source that file, so `npm`/`node` can be silently
# missing from PATH here even though they work fine in an opened terminal.
export NVM_DIR="${NVM_DIR:-/usr/local/share/nvm}"
if [ -s "$NVM_DIR/nvm.sh" ]; then
  # shellcheck disable=SC1091
  source "$NVM_DIR/nvm.sh"
fi
echo "==> node: $(command -v node || echo NOT FOUND) ($(node --version 2>&1))"
echo "==> npm:  $(command -v npm || echo NOT FOUND) ($(npm --version 2>&1))"

echo "==> Setting up backend (Python venv)..."
python3 -m venv backend/.venv
backend/.venv/bin/pip install --upgrade pip -q
backend/.venv/bin/pip install -q -r backend/requirements.txt

echo "==> Setting up frontend (npm install)..."
npm install --prefix frontend

echo "==> Setup complete."
