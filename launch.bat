@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 437 >nul

title LinkedIn Job Finder

echo.
echo  LinkedIn Job Finder - PC launcher
echo  =================================
echo.
echo  Starts:
echo    1. Python venv if needed
echo    2. SSH tunnel to http://127.0.0.1:8000
echo    3. Codex PC worker for Telegram /apply
echo    4. Opens the web dashboard in your browser
echo.
echo  Leave this window open. Ctrl+C stops the worker and closes the tunnel.
echo.

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"
set "VENV_PY=%BACKEND%\venv\Scripts\python.exe"
set "VENV_PIP=%BACKEND%\venv\Scripts\pip.exe"
set "SSH_KEY=%USERPROFILE%\.ssh\ot_clinic_deploy"
set "VPS_USER=deploy"
set "VPS_HOST=156.253.5.183"
set "LOCAL_PORT=8000"
set "REMOTE_PORT=8001"
set "TUNNEL_TITLE=LinkedIn Jobs Tunnel"
set "TUNNEL_BAT=%ROOT%deploy\ssh_tunnel.bat"
set "JOB_SEARCH_WORKSPACE=C:\Users\Ramin\Desktop\Job Search"
set "CODEX_APPLY_TIMEOUT_SEC=900"
set "WORKER_REMOTE_URL=http://127.0.0.1:%LOCAL_PORT%"

REM Windows HTTP proxies break localhost tunnel calls.
set "HTTP_PROXY="
set "HTTPS_PROXY="
set "ALL_PROXY="
set "http_proxy="
set "https_proxy="
set "all_proxy="
set "NO_PROXY=127.0.0.1,localhost"
set "no_proxy=127.0.0.1,localhost"

if not exist "%BACKEND%\requirements.txt" goto err_backend
if not exist "%SSH_KEY%" goto err_ssh_key

where ssh >nul 2>&1
if errorlevel 1 goto err_ssh

if not exist "%VENV_PY%" goto make_venv
goto after_venv

:make_venv
echo  Creating Python virtual environment...
python -m venv "%BACKEND%\venv"
if errorlevel 1 goto err_venv
echo  Installing dependencies...
"%VENV_PIP%" install -r "%BACKEND%\requirements.txt"
if errorlevel 1 goto err_deps
goto after_venv

:after_venv
REM Preload WORKER_API_SECRET from backend\.env without testing its value
REM in an IF (secrets can contain characters that break cmd parsing).
if defined WORKER_API_SECRET goto after_secret
if not exist "%BACKEND%\.env" goto after_secret
for /f "usebackq tokens=1,* delims== eol=#" %%A in ("%BACKEND%\.env") do (
    if /I "%%~A"=="WORKER_API_SECRET" set "WORKER_API_SECRET=%%~B"
)
:after_secret

if not exist "%BACKEND%\.env" (
    echo WARNING: backend\.env not found - copy backend\.env.example and fill keys.
    echo.
)

set "PATH=%ProgramFiles%\nodejs;%PATH%"
if exist "%ProgramFiles%\nodejs\npm.cmd" goto maybe_build_frontend
if exist "%FRONTEND%\dist\index.html" goto after_frontend
echo  NOTE: Node.js not found and no frontend\dist yet.
echo  Dashboard still opens through the VPS tunnel.
echo.
goto after_frontend

:maybe_build_frontend
if exist "%FRONTEND%\dist\index.html" goto after_frontend
echo  Building frontend first time...
pushd "%FRONTEND%"
call npm install
call npm run build
if errorlevel 1 echo  WARNING: Frontend build failed. Dashboard via tunnel may still work.
popd
:after_frontend

if not exist "%TUNNEL_BAT%" goto err_tunnel_bat

echo  Checking port %LOCAL_PORT%...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /C:":%LOCAL_PORT%" ^| findstr "LISTENING"') do (
    echo   Freeing port %LOCAL_PORT% PID %%p ...
    taskkill /PID %%p /F >nul 2>&1
)
ping -n 2 127.0.0.1 >nul

echo  Starting SSH tunnel with auto-reconnect...
start "%TUNNEL_TITLE%" /MIN "%TUNNEL_BAT%"

echo  Waiting for tunnel on port %LOCAL_PORT%...
set /a _tries=0
:wait_tunnel
set /a _tries+=1
netstat -ano | findstr /C:":%LOCAL_PORT%" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 goto tunnel_ready
if %_tries% GEQ 45 goto err_tunnel_timeout
ping -n 2 127.0.0.1 >nul
goto wait_tunnel

:tunnel_ready
echo  Waiting for API through tunnel...
set /a _api_tries=0
:wait_api
set /a _api_tries+=1
curl.exe -s --noproxy "*" -m 3 -o NUL -w "%%{http_code}" "http://127.0.0.1:%LOCAL_PORT%/api/health" | findstr "200" >nul 2>&1
if not errorlevel 1 goto api_ready
if %_api_tries% GEQ 30 (
    echo WARNING: Tunnel is up but /api/health did not return 200 yet.
    goto api_ready
)
ping -n 2 127.0.0.1 >nul
goto wait_api

:api_ready
echo  Tunnel ready.
echo  Opening dashboard: http://127.0.0.1:%LOCAL_PORT%/
start http://127.0.0.1:%LOCAL_PORT%/

echo.
echo  Starting Codex PC worker...
echo    API:       %WORKER_REMOTE_URL%
echo    Workspace: %JOB_SEARCH_WORKSPACE%
echo    Tip: run "agent login" once if needed.
echo.

cd /d "%BACKEND%"
"%VENV_PY%" -m app.worker.runner
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo  Worker stopped - closing tunnel...
call :cleanup_tunnel
echo  Done.
if not "%EXIT_CODE%"=="0" pause
endlocal
exit /b %EXIT_CODE%

:cleanup_tunnel
taskkill /FI "WINDOWTITLE eq %TUNNEL_TITLE*" /T /F >nul 2>&1
exit /b 0

:err_backend
echo ERROR: backend folder not found.
goto fail

:err_ssh_key
echo ERROR: SSH key not found:
echo   %SSH_KEY%
goto fail

:err_ssh
echo ERROR: ssh not found. Install OpenSSH Client from Windows Settings.
goto fail

:err_venv
echo ERROR: Failed to create venv. Is Python installed?
goto fail

:err_deps
echo ERROR: Failed to install dependencies.
goto fail

:err_tunnel_bat
echo ERROR: Missing tunnel script:
echo   %TUNNEL_BAT%
goto fail

:err_tunnel_timeout
echo ERROR: Tunnel did not open on port %LOCAL_PORT% within 45s.
echo Check the "%TUNNEL_TITLE%" window for SSH errors.
call :cleanup_tunnel
goto fail

:fail
echo.
pause
endlocal
exit /b 1
