@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [setup] Creating virtual environment in .venv
  where py >nul 2>nul
  if %errorlevel%==0 (
    py -3 -m venv .venv
  ) else (
    python -m venv .venv
  )
)

echo [setup] Activating virtual environment
call ".venv\Scripts\activate.bat"
if errorlevel 1 (
  echo [error] Failed to activate .venv
  exit /b 1
)

echo [setup] Installing/updating project dependencies
python -m pip install --upgrade pip
if errorlevel 1 exit /b 1
python -m pip install -e .
if errorlevel 1 exit /b 1

if "%SAMS_SETUP_DATA_FILE%"=="" set "SAMS_SETUP_DATA_FILE=%CD%\sams_web\setup_data.json"

if "%HOST%"=="" set "HOST=127.0.0.1"
if "%PORT%"=="" set "PORT=8000"

echo [run] Starting SAMS Web on http://%HOST%:%PORT%
echo [run] Press Ctrl+C to stop
python -m uvicorn sams_web.main:app --reload --host %HOST% --port %PORT%

endlocal
