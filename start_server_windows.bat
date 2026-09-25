@echo off
rem ==========================================================================
rem  SAMS Web - production start script for a Windows SERVER.
rem
rem  Run by the Windows service (docs\server_installation.md, section 7) and
rem  for the manual first run (section 6). Differences from the workstation
rem  launcher start_webapp_windows.bat:
rem    - never installs or upgrades packages; installing is a separate,
rem      deliberate step from requirements.lock.txt
rem    - no --reload
rem    - listens on the network (0.0.0.0) so lab PCs can connect; the
rem      Windows firewall rule decides who may reach it
rem    - does NOT set SAMS_SETUP_DATA_FILE, so the path in .env is honoured
rem
rem  NO LOGIN EXISTS YET: anyone who can reach this port can change data.
rem  Keep it on the lab network only - never expose it to the internet.
rem
rem  Override with SAMS_HOST / SAMS_PORT (e.g. in the service environment).
rem ==========================================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [error] No .venv in %CD% - install first, see docs\server_installation.md section 5.
  exit /b 1
)
if not exist ".env" (
  echo [error] No .env in %CD% - it must define SAMS_DATABASE_URL, see section 4.
  exit /b 1
)

if "%SAMS_HOST%"=="" set "SAMS_HOST=0.0.0.0"
if "%SAMS_PORT%"=="" set "SAMS_PORT=8502"

rem One worker on purpose: the settings file is written by a single process.
echo [run] SAMS Web listening on %SAMS_HOST%:%SAMS_PORT% - press Ctrl+C to stop
".venv\Scripts\python.exe" -m uvicorn sams_web.main:app --host %SAMS_HOST% --port %SAMS_PORT% --workers 1
exit /b %ERRORLEVEL%
