@echo off
setlocal enabledelayedexpansion
title Gleenergy - Start and Share
cd /d "%~dp0.."

REM ===== Find Python =====
where py >nul 2>&1 && (set "PY=py") || (set "PY=python")
%PY% --version >nul 2>&1
if errorlevel 1 (
  echo.
  echo  Python was not found. Install it from https://www.python.org/downloads/
  echo  and tick "Add python.exe to PATH", then run this again.
  echo.
  pause & exit /b
)

REM ===== Install packages the first time =====
%PY% -m pip show uvicorn >nul 2>&1
if errorlevel 1 (
  echo  First-time setup: installing required packages (one minute)...
  %PY% -m pip install -r requirements.txt
)

REM ===== Start the web server in its own window =====
echo  Starting the system server...
start "Gleenergy Server" cmd /k "%PY% -m uvicorn app:app --host 0.0.0.0 --port 8000"

REM ===== Find this PC's local network address (the active internet adapter) =====
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "try{((Get-NetIPConfiguration | Where-Object {$_.IPv4DefaultGateway -ne $null -and $_.NetAdapter.Status -eq 'Up'} | Select-Object -First 1).IPv4Address.IPAddress)}catch{''}"`) do set "LANIP=%%i"

REM ===== Start ngrok tunnel (only if ngrok is installed / in this folder) =====
set "NGROK_OK=0"
where ngrok >nul 2>&1 && set "NGROK_OK=1"
if "!NGROK_OK!"=="1" (
  echo  Starting the public tunnel (ngrok)...
  start "ngrok tunnel" cmd /k "ngrok http 8000"
) else (
  echo  ngrok not found - the remote link will be skipped.
  echo  ^(See README "Path B" to set up ngrok for remote testers.^)
)

REM ===== Wait for things to come online, then read the public URL from ngrok =====
echo  Waiting for the server and tunnel to come online...
set "PUBURL="
if "!NGROK_OK!"=="1" (
  for /f "usebackq delims=" %%u in (`powershell -NoProfile -Command "$u='';1..8 ^| %%{ try{ $r=Invoke-RestMethod http://127.0.0.1:4040/api/tunnels -TimeoutSec 3; $u=($r.tunnels ^| Where-Object {$_.proto -eq 'https'} ^| Select-Object -First 1 -ExpandProperty public_url); if(-not $u){$u=$r.tunnels[0].public_url}; if($u){break} }catch{}; Start-Sleep -Seconds 2 }; $u"`) do set "PUBURL=%%u"
) else (
  timeout /t 4 >nul
)

REM ===== Show the links =====
cls
echo ===============================================================
echo             GLEENERGY SYSTEM - TEST SESSION LINKS
echo ===============================================================
echo.
echo   On THIS computer:         http://localhost:8000
if defined LANIP (
  echo   Same Wi-Fi / office:      http://!LANIP!:8000
) else (
  echo   Same Wi-Fi / office:      run 'ipconfig' to find your IPv4 address, then http://THAT-IP:8000
)
if defined PUBURL (
  echo   Remote testers ^(share^):   !PUBURL!
) else (
  if "!NGROK_OK!"=="1" (
    echo   Remote testers:           tunnel starting - check the "ngrok tunnel" window for the https link.
  ) else (
    echo   Remote testers:           ngrok not installed - see README "Path B".
  )
)
echo.
echo ---------------------------------------------------------------
echo   Two helper windows opened: "Gleenergy Server" and "ngrok tunnel".
echo   KEEP THEM OPEN during testing. Closing them ends the session.
echo.
echo   SECURITY: the remote link has no password and exposes all data
echo   to anyone who has it. Share it privately and close ngrok when done.
echo ---------------------------------------------------------------
echo.

REM ===== Open the app on this computer =====
start http://localhost:8000

echo  You can close THIS window now (the server and tunnel keep running).
echo.
pause
endlocal
