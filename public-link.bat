@echo off
setlocal
cd /d "%~dp0"

rem ---------------------------------------------------------------------------
rem  public-link.bat - start the app + a public Cloudflare link, in your own
rem  windows so they keep running even after Claude Code closes.
rem  Double-click this file. Keep BOTH windows open while you want the link.
rem ---------------------------------------------------------------------------
title SHG public link

rem --- find cloudflared (a single exe next to this file) ---------------------
set "CF=%~dp0cloudflared.exe"
if not exist "%CF%" (
  echo.
  echo cloudflared.exe was not found next to this file.
  echo Download it once from:
  echo   https://github.com/cloudflare/cloudflared/releases/latest
  echo choose cloudflared-windows-amd64.exe and save it in this folder as cloudflared.exe
  echo.
  pause
  exit /b 1
)

rem --- start the app in its own window if it isn't already running -----------
curl.exe -s -f -o nul -m 2 http://localhost:8000/api/status >nul 2>&1
if errorlevel 1 (
  echo Starting the app...
  start "SHG Reports" cmd /k run.bat
)

rem --- wait for the app to answer (up to ~90 s) -------------------------------
echo Waiting for the app...
for /l %%i in (1,1,60) do (
  curl.exe -s -f -o nul -m 2 http://localhost:8000/api/status >nul 2>&1 && goto :app_ready
  ping -n 2 127.0.0.1 >nul
)
echo.
echo Could not reach http://localhost:8000. Open run.bat first, then run this again.
pause
exit /b 1

:app_ready
rem --- open the public tunnel in its own window -------------------------------
echo Opening the public link...
start "Public link (keep this open)" cmd /k "%CF%" tunnel --url http://localhost:8000

echo.
echo ============================================================
echo   Two windows are now open:
echo     1. SHG Reports   - the app (http://localhost:8000)
echo     2. Public link   - shows your https://...trycloudflare.com URL
echo.
echo   Your public link is printed inside the "Public link" window.
echo   Keep both windows open. Closing "Public link" stops sharing.
echo ============================================================
echo.
pause
