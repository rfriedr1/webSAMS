#!/usr/bin/env bash
# SAMS Web — install (first time) and run, on macOS / Linux.
#
#   ./start_webapp_macos.sh            run on http://127.0.0.1:8502 (this Mac only)
#   HOST=0.0.0.0 ./start_webapp_macos.sh   also reachable from other lab PCs
#   SAMS_DEV=1 ./start_webapp_macos.sh     auto-reload on code changes (developers)
#
# Needs: Python 3.11+ and a .env file (copy .env.example). See docs/quickstart.md.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if [[ ! -f ".env" ]]; then
  echo
  echo "[setup] No .env file found."
  echo "        Copy .env.example to .env and fill in SAMS_DATABASE_URL:"
  echo "            cp .env.example .env"
  echo "        then run this script again."
  exit 1
fi

# Pick the newest Python 3.11+ on this machine. Plain `python3` is often the
# OS's own 3.9 on macOS, which cannot install the pinned packages.
pick_python() {
  for c in python3.13 python3.12 python3.11 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      echo "$c"; return 0
    fi
  done
  return 1
}

if [[ -x ".venv/bin/python" ]] && ! .venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
  echo "[setup] .venv was created with $(.venv/bin/python --version 2>&1), which is too old."
  echo "        Delete the .venv folder and run this script again."
  exit 1
fi

if [[ ! -x ".venv/bin/python" ]]; then
  PY="$(pick_python)" || {
    echo "[setup] No Python 3.11 or newer found. Install Python 3.13 from https://www.python.org/downloads/"
    echo "        (or: brew install python@3.13) and run this script again."
    exit 1
  }
  echo "[setup] Creating the Python environment in .venv with $("$PY" --version) (first run only)"
  "$PY" -m venv .venv
fi

# Install the exact tested package versions. Skipped when nothing changed,
# so a normal start takes seconds and works without internet.
STAMP=".venv/.installed-from"
WANT="$(cat requirements.lock.txt pyproject.toml | shasum | cut -c1-16)"
if [[ ! -f "$STAMP" || "$(cat "$STAMP")" != "$WANT" ]]; then
  echo "[setup] Installing packages (first run, or requirements changed)"
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.lock.txt
  .venv/bin/python -m pip install --quiet --no-deps -e .
  echo "$WANT" > "$STAMP"
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8502}"
# A plain string, not an array: macOS ships bash 3.2, where expanding an
# empty array under `set -u` is an "unbound variable" error.
RELOAD=""
[[ "${SAMS_DEV:-}" == "1" ]] && RELOAD="--reload"

echo
echo "[run] SAMS Web is starting on http://${HOST}:${PORT}/"
[[ "$HOST" == "127.0.0.1" ]] && echo "[run] (only this computer can open it — set HOST=0.0.0.0 for the lab network)"
echo "[run] Press Ctrl+C to stop"
echo
# shellcheck disable=SC2086  # $RELOAD is intentionally unquoted: empty or a single flag
exec .venv/bin/python -m uvicorn sams_web.main:app --host "$HOST" --port "$PORT" $RELOAD
