@echo off
rem SAMS Web - install (first time) and run, on Windows.
rem
rem   Double-click, or from a prompt:   start_webapp_windows.bat
rem   set HOST=0.0.0.0  before running  -> also reachable from other lab PCs
rem   set SAMS_DEV=1    before running  -> auto-reload on code changes (developers)
rem
rem Needs: Python 3.11+ (python.org, "Add to PATH" ticked) and a .env file
rem (copy .env.example). See docs\quickstart.md. For a permanent server that
rem runs as a Windows service, see docs\server_installation.md instead.
setlocal EnableDelayedExpansion
cd /d "%~dp0"

if not exist ".env" (
  echo.
  echo [setup] No .env file found.
  echo         Copy .env.example to .env and fill in SAMS_DATABASE_URL, then run this again.
  echo.
  pause
  exit /b 1
)

rem An existing .venv made with an old Python cannot install the pinned packages.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>nul
  if errorlevel 1 (
    echo [setup] The .venv folder was created with an old Python. Delete .venv and run this again.
    pause
    exit /b 1
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo [setup] Creating the Python environment in .venv - first run only
  rem Newest 3.11+ wins: the py launcher (python.org installs) first, then whatever "python" is.
  set "PYCMD="
  for %%v in (3.13 3.12 3.11) do (
    if not defined PYCMD ( py -%%v -c "pass" >nul 2>nul && set "PYCMD=py -%%v" )
  )
  if not defined PYCMD ( python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PYCMD=python" )
  if not defined PYCMD (
    echo [error] No Python 3.11 or newer found. Install Python 3.13 from https://www.python.org/downloads/
    echo         and tick "Add python.exe to PATH", then run this again.
    pause
    exit /b 1
  )
  call %PYCMD% -m venv .venv
  if errorlevel 1 (
    echo [error] Could not create .venv.
    pause
    exit /b 1
  )
)

rem Install the exact tested versions. Skipped when nothing changed, so a
rem normal start takes seconds and works without internet.
set "STAMP=.venv\installed-from.txt"
set "WANT="
for /f "usebackq delims=" %%h in (`certutil -hashfile requirements.lock.txt SHA256 ^| findstr /v /i "hash"`) do if not defined WANT set "WANT=%%h"
set "HAVE="
if exist "%STAMP%" set /p HAVE=<"%STAMP%"
if not "%HAVE%"=="%WANT%" (
  echo [setup] Installing packages - first run, or requirements changed
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.lock.txt
  if errorlevel 1 ( echo [error] Package installation failed. & pause & exit /b 1 )
  ".venv\Scripts\python.exe" -m pip install --quiet --no-deps -e .
  if errorlevel 1 ( echo [error] Package installation failed. & pause & exit /b 1 )
  >"%STAMP%" echo %WANT%
)

if "%HOST%"=="" set "HOST=127.0.0.1"
if "%PORT%"=="" set "PORT=8502"
set "RELOAD="
if "%SAMS_DEV%"=="1" set "RELOAD=--reload"

echo.
echo [run] SAMS Web is starting on http://%HOST%:%PORT%/
if "%HOST%"=="127.0.0.1" echo [run] (only this computer can open it - set HOST=0.0.0.0 for the lab network)
echo [run] Press Ctrl+C to stop
echo.
".venv\Scripts\python.exe" -m uvicorn sams_web.main:app --host %HOST% --port %PORT% %RELOAD%
if errorlevel 1 pause
endlocal
