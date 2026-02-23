# web-SAMS Server Installation Guide

## Purpose

This guide describes how to install and run `web-SAMS` on a new server.

It covers:
- system prerequisites
- application setup
- environment configuration (`.env`)
- database connectivity
- starting the app
- production service setup (Linux `systemd`)
- basic troubleshooting

## 1. Prerequisites

## Required

- Python `3.11+`
- Network access from the server to the MySQL database server
- Valid MySQL credentials for the SAMS database

## Recommended (Linux server)

- `git`
- `python3-venv`
- `build-essential` (or equivalent compiler tools)

Example (Debian/Ubuntu):

```bash
sudo apt update
sudo apt install -y git python3 python3-venv build-essential
```

## 2. Get the Project on the Server

Copy the project folder to the server (for example via `git clone`, `scp`, or shared storage).

Example:

```bash
git clone <your-repo-url> webSAMS
cd webSAMS
```

## 3. Create and Configure the Local Environment File

The app now automatically loads local environment files:
- `.env`
- `.env.local`

These files are ignored by git (`.gitignore`) and should contain your real connection string.

Create `.env` in the project root:

```env
SAMS_DATABASE_URL=mysql+pymysql://<USER>:<PASSWORD>@<HOST>/<DATABASE>
SAMS_SETUP_DATA_FILE=sams_web/setup_data.json

# Optional
# SAMS_DEBUG=false
# SAMS_SQL_ECHO=false
```

Important:
- `SAMS_DATABASE_URL` is required.
- `SAMS_SETUP_DATA_FILE` should point to a writable file location.

## 4. Create the Virtual Environment and Install Dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Notes:
- `python-dotenv` is included in project dependencies and is used to auto-load `.env`.
- Re-run `pip install -e .` after pulling updates.

## 5. Verify Basic Startup (Manual)

Run locally on the server first:

```bash
source .venv/bin/activate
python -m uvicorn sams_web.main:app --host 127.0.0.1 --port 8000
```

Open in browser (from the server or via SSH tunnel):
- UI: `http://127.0.0.1:8000/`
- API Docs: `http://127.0.0.1:8000/docs`

If startup fails because of missing configuration, the app will report that `SAMS_DATABASE_URL` is required.

## 6. Platform-Specific Setup (macOS / Windows)

This section provides explicit setup steps for macOS and Windows in addition to the generic/Linux instructions above.

## 6.1 macOS Setup (Manual)

## Prerequisites (macOS)

- Python `3.11+` installed (for example via python.org or Homebrew)
- Terminal access
- Network access to the MySQL database server

Optional (Homebrew example):

```bash
brew install python
```

## Setup Steps (macOS)

```bash
cd /path/to/webSAMS
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Create `.env` in the project root:

```env
SAMS_DATABASE_URL=mysql+pymysql://<USER>:<PASSWORD>@<HOST>/<DATABASE>
SAMS_SETUP_DATA_FILE=sams_web/setup_data.json
```

Run:

```bash
source .venv/bin/activate
python -m uvicorn sams_web.main:app --host 127.0.0.1 --port 8000
```

Open:
- `http://127.0.0.1:8000/`

## 6.2 Windows Setup (Manual)

## Prerequisites (Windows)

- Python `3.11+` installed (recommended: installer from python.org)
- Command Prompt (`cmd`) or PowerShell
- Network access to the MySQL database server

Important:
- During Python installation, enable the option to add Python to `PATH` (if available).

## Setup Steps (Windows CMD)

```bat
cd C:\path\to\webSAMS
py -3 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -e .
```

Create `.env` in the project root:

```env
SAMS_DATABASE_URL=mysql+pymysql://<USER>:<PASSWORD>@<HOST>/<DATABASE>
SAMS_SETUP_DATA_FILE=sams_web/setup_data.json
```

Run:

```bat
.venv\Scripts\activate.bat
python -m uvicorn sams_web.main:app --host 127.0.0.1 --port 8000
```

Open:
- `http://127.0.0.1:8000/`

## Setup Steps (Windows PowerShell)

```powershell
cd C:\path\to\webSAMS
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python -m uvicorn sams_web.main:app --host 127.0.0.1 --port 8000
```

If PowerShell blocks activation scripts, you may need (PowerShell as current user):

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## 6.3 Startup Scripts (Optional, macOS / Windows)

The repository includes helper scripts:
- macOS: `start_webapp_macos.sh`
- Windows: `start_webapp_windows.bat`

These scripts:
- create `.venv` if missing
- install dependencies
- start `uvicorn`

They use your `.env` automatically because the app loads `.env` in `sams_web/config.py`.

For a first-time setup on a workstation, these scripts are the fastest option.

## 7. Production Run (Linux) with systemd

For production, do **not** use `--reload`.

Create a service file:

`/etc/systemd/system/websams.service`

```ini
[Unit]
Description=web-SAMS FastAPI service
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/webSAMS
EnvironmentFile=/opt/webSAMS/.env
ExecStart=/opt/webSAMS/.venv/bin/python -m uvicorn sams_web.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Then enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable websams
sudo systemctl start websams
sudo systemctl status websams
```

## 8. Reverse Proxy (Recommended)

For browser access in a lab network, run `web-SAMS` behind a reverse proxy (for example Nginx).

Typical setup:
- Nginx listens on `80/443`
- proxies to `127.0.0.1:8000`

This gives:
- stable local URL
- TLS termination (HTTPS)
- better process isolation

## 9. File Permissions and Runtime Notes

- Ensure the service user can read:
  - project files
  - `.env`
- Ensure the service user can write:
  - `sams_web/setup_data.json` (or the file configured via `SAMS_SETUP_DATA_FILE`)

## 10. Troubleshooting Checklist

## App does not start

- Check `.env` exists in project root
- Check `SAMS_DATABASE_URL` is present and valid
- Run:

```bash
source .venv/bin/activate
python -m pip install -e .
python -m uvicorn sams_web.main:app --host 127.0.0.1 --port 8000
```

## Cannot connect to database

- Verify DB host/IP and port are reachable from the server
- Verify username/password
- Verify DB name is correct
- Verify MySQL user has required permissions

## Setup changes are not saved

- Check write permission for `SAMS_SETUP_DATA_FILE`
- Confirm the path in `.env`

## 11. Updating web-SAMS on the Server

After code updates:

```bash
cd /opt/webSAMS
source .venv/bin/activate
python -m pip install -e .
sudo systemctl restart websams
```

## 12. Quick Validation Commands

From project root:

```bash
source .venv/bin/activate
python3 -m compileall sams_web
```

Optional runtime smoke check:

```bash
source .venv/bin/activate
python - <<'PY'
from sams_web.main import app
print("app-import-ok")
PY
```
