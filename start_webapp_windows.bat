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
setlocal
cd /d "%~dp0"

if not exist ".env" (
  echo.
  echo [setup] No .env file found.
  echo         Copy .env.example to .env and fill in SAMS_DATABASE_URL, then run this again.
  echo.
  pause
  exit /b 1
)

rem --- Python environment --------------------------------------------------
rem Deliberately built with goto, not an "if ( ... )" block: cmd expands every
rem %VAR% in a block when it READS the block, before any line in it runs. The
rem earlier version set PYCMD inside such a block and then ran "%PYCMD% -m venv"
rem in the same block - which expanded to just "-m venv .venv" and failed.

if not exist ".venv\Scripts\python.exe" goto :create_venv

rem An existing .venv made with an old Python cannot install the pinned packages.
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 goto :venv_too_old
goto :venv_ready

:create_venv
echo [setup] Creating the Python environment in .venv - first run only
rem Newest tested version wins (3.14 and 3.13 are tested), via the py launcher
rem that python.org installs. Then any newer 3.x the launcher knows, then "python".
set "PYCMD="
for %%v in (3.14 3.13 3.12 3.11) do (
  if not defined PYCMD ( py -%%v -c "pass" >nul 2>nul && set "PYCMD=py -%%v" )
)
if not defined PYCMD ( py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PYCMD=py -3" )
if not defined PYCMD ( python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PYCMD=python" )
if not defined PYCMD goto :no_python

rem Top level, outside any block: %PYCMD% now holds the value set above.
echo [setup] Using: %PYCMD%
%PYCMD% -m venv .venv
if errorlevel 1 goto :venv_failed
if not exist ".venv\Scripts\python.exe" goto :venv_failed

:venv_ready

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
exit /b 0

:no_python
echo [error] No Python 3.11 or newer found. Install Python 3.14 from https://www.python.org/downloads/
echo         and tick "Add python.exe to PATH", then run this again.
pause
exit /b 1

:venv_too_old
echo [setup] The .venv folder was created with an old Python. Delete .venv and run this again.
pause
exit /b 1

:venv_failed
echo [error] Could not create .venv with: %PYCMD%
echo         If a half-created .venv folder exists, delete it and run this again.
pause
exit /b 1
