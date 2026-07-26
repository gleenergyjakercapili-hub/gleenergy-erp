@echo off
title Gleenergy System Server
cd /d "%~dp0.."

REM --- Find Python (the "py" launcher, or fall back to "python") ---
where py >nul 2>&1 && (set "PY=py") || (set "PY=python")
%PY% --version >nul 2>&1
if errorlevel 1 (
  echo.
  echo  Python was not found on this computer.
  echo  Please install it from https://www.python.org/downloads/
  echo  and tick "Add python.exe to PATH" during setup, then run this again.
  echo.
  pause
  exit /b
)

REM --- Install required packages the first time only ---
%PY% -m pip show uvicorn >nul 2>&1
if errorlevel 1 (
  echo.
  echo  First-time setup: installing required packages...
  echo  (this only happens once and may take a minute)
  echo.
  %PY% -m pip install -r requirements.txt
)

echo.
echo  ============================================================
echo    GLEENERGY SYSTEM is starting up...
echo.
echo    Your browser will open automatically at:
echo        http://localhost:8000
echo.
echo    KEEP THIS WINDOW OPEN - it runs the server.
echo    To STOP the system: close this window (or press Ctrl+C).
echo  ============================================================
echo.

REM --- Open the browser a few seconds after the server boots ---
start "" /min cmd /c "timeout /t 4 >nul & start http://localhost:8000"

REM --- Start the server (this line keeps running) ---
%PY% -m uvicorn app:app --host 0.0.0.0 --port 8000

echo.
echo  Server stopped. You can close this window.
pause >nul
