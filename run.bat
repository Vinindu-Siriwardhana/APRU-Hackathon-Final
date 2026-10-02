@echo off
setlocal
cd /d "%~dp0"
rem The same file is started a second time, in the background, to open the browser
rem once the app answers (see :open_when_ready at the bottom).
if "%~1"=="--open-when-ready" goto :open_when_ready
title SHG Reports

rem ---------------------------------------------------------------------------
rem  SHG Reports - Windows launcher. Double-click this file.
rem  First run installs everything into the .venv folder (a few minutes,
rem  about 100 MB download - do it the day before, on a good connection).
rem ---------------------------------------------------------------------------

if not exist "backend\requirements.txt" goto :inside_zip

rem --- find Python 3.10 or newer: the "py" launcher first, then "python" ------------
set "PY="
call :try_python py -3
if not defined PY call :try_python python
if not defined PY goto :no_python

rem --- create the environment (again, if a previous attempt was left half-made) ----
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys" >nul 2>nul || rmdir /s /q ".venv"
)
if exist ".venv" if not exist ".venv\Scripts\python.exe" rmdir /s /q ".venv"
if exist ".venv\Scripts\python.exe" goto :have_venv
echo Creating the Python environment...
%PY% -m venv .venv
if errorlevel 1 goto :venv_failed
:have_venv
set "VPY=.venv\Scripts\python.exe"

rem --- install the libraries when requirements.txt is new or has changed -----------
rem .venv\installed.txt holds a fingerprint of backend\requirements.txt
"%VPY%" -c "import hashlib,pathlib,sys; h=hashlib.sha256(pathlib.Path('backend/requirements.txt').read_bytes()).hexdigest(); m=pathlib.Path('.venv/installed.txt'); sys.exit(0 if m.exists() and m.read_text().strip()==h else 1)"
if not errorlevel 1 goto :check_port
echo.
echo Installing libraries. This takes a few minutes the first time...
echo.
"%VPY%" -m pip install --disable-pip-version-check -q --upgrade pip
"%VPY%" -m pip install --disable-pip-version-check -r backend\requirements.txt
if errorlevel 1 goto :pip_failed
"%VPY%" -c "import hashlib,pathlib; pathlib.Path('.venv/installed.txt').write_text(hashlib.sha256(pathlib.Path('backend/requirements.txt').read_bytes()).hexdigest())"

rem --- is port 8000 free? ----------------------------------------------------------
:check_port
"%VPY%" -c "import socket,sys; s=socket.socket(); s.settimeout(3); sys.exit(0 if s.connect_ex(('127.0.0.1', 8000)) else 1)"
if errorlevel 1 goto :port_busy

:run
echo.
echo ============================================================
echo   SHG Reports is starting...
echo   Your browser opens http://localhost:8000 by itself once the
echo   app is ready (up to a minute the first time).
echo   Keep this window open. Close it to stop the app.
echo ============================================================
echo.
if exist ".venv\server_stopped" del ".venv\server_stopped" >nul 2>nul
start "" /b cmd /c ""%~f0" --open-when-ready"
cd backend
"..\.venv\Scripts\python.exe" -m uvicorn app.api:app --port 8000
set "RC=%ERRORLEVEL%"
cd ..
echo stopped> ".venv\server_stopped"
rem Ctrl+C or closing the window is a normal stop, not an error
if "%RC%"=="0" goto :stopped
if "%RC%"=="-1073741510" goto :stopped
if "%RC%"=="3221225786" goto :stopped
if "%RC%"=="130" goto :stopped
goto :server_failed

:stopped
echo.
echo SHG Reports has stopped. You can close this window.
exit /b 0

rem --- helpers -------------------------------------------------------------------
:try_python
rem Use this Python if it exists and is 3.10 or newer.
%* -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=%*"
exit /b 0

:open_when_ready
rem Ask the app every second, for up to 90 seconds, whether it is ready.
rem curl.exe and PowerShell are both part of Windows 10 and 11.
set "ASK=powershell -NoProfile -Command "try { $null = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://localhost:8000/api/status; exit 0 } catch { exit 1 }""
where curl.exe >nul 2>nul && set "ASK=curl.exe -s -f -o nul -m 2 http://localhost:8000/api/status"
for /l %%i in (1,1,90) do (
  if exist ".venv\server_stopped" exit /b 0
  %ASK% >nul 2>nul && (
    start "" http://localhost:8000
    exit /b 0
  )
  ping -n 2 127.0.0.1 >nul
)
echo.
echo The app is taking longer than usual. When this window says
echo "Application startup complete", open http://localhost:8000 in your browser.
exit /b 0

rem --- problems ------------------------------------------------------------------
:inside_zip
echo.
echo It looks like run.bat was opened from inside the zip file.
echo Right-click the zip, choose "Extract All", then open the extracted
echo shg-digitiser folder and double-click run.bat there.
goto :fail

:no_python
echo.
echo Python 3.10 or newer was not found.
echo Install Python 3.12 from https://www.python.org/downloads/windows/
echo and tick "Add python.exe to PATH" on the first screen of the installer.
echo Then double-click run.bat again.
goto :fail

:venv_failed
if exist ".venv" rmdir /s /q ".venv"
echo.
echo Could not create the Python environment in the .venv folder.
echo Try moving the shg-digitiser folder somewhere simple, like C:\shg-digitiser
echo (not inside OneDrive), then double-click run.bat again.
goto :fail

:pip_failed
echo.
echo Installing the libraries failed - see the messages above.
echo Check your internet connection and double-click run.bat again.
echo If it still fails, delete the .venv folder and try once more.
goto :fail

:port_busy
echo.
echo SHG Reports is probably already running: open http://localhost:8000,
echo or close the other SHG Reports window and double-click run.bat again.
echo (Another program is using port 8000.)
goto :fail

:server_failed
echo.
echo The app stopped with an error - see the messages above.
goto :fail

:fail
echo.
pause
exit /b 1
