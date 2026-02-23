#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "[setup] Creating virtual environment in .venv"
  python3 -m venv .venv
fi

echo "[setup] Activating virtual environment"
source ".venv/bin/activate"

echo "[setup] Installing/updating project dependencies"
python -m pip install --upgrade pip
python -m pip install -e .

export SAMS_SETUP_DATA_FILE="${SAMS_SETUP_DATA_FILE:-$SCRIPT_DIR/sams_web/setup_data.json}"

PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"

echo "[run] Starting SAMS Web on http://${HOST}:${PORT}"
echo "[run] Press Ctrl+C to stop"
exec python -m uvicorn sams_web.main:app --reload --host "$HOST" --port "$PORT"
