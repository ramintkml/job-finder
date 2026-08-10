@echo off
setlocal EnableExtensions
chcp 437 >nul
title LinkedIn Jobs Tunnel

set "SSH_KEY=%USERPROFILE%\.ssh\ot_clinic_deploy"
set "VPS_HOST=156.253.5.183"
set "VPS_USER=deploy"
set "LOCAL_PORT=8000"
set "REMOTE_PORT=8001"

echo.
echo  LinkedIn Job Finder SSH tunnel
echo  ==============================
echo  Forwards localhost:%LOCAL_PORT% to VPS 127.0.0.1:%REMOTE_PORT%
echo  Reconnects automatically if the link drops.
echo  Close this window to stop the tunnel.
echo.
echo  NOTE: While connected, this window stays on the SSH line.
echo  That is normal - it means the tunnel is UP.
echo  You only see a new message if the connection drops.
echo.

if not exist "%SSH_KEY%" (
    echo ERROR: SSH key not found: %SSH_KEY%
    pause
    exit /b 1
)

:reconnect
echo [%TIME%] Connecting to %VPS_USER%@%VPS_HOST% ...
ssh -i "%SSH_KEY%" -o IdentitiesOnly=yes -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o TCPKeepAlive=yes -N -L %LOCAL_PORT%:127.0.0.1:%REMOTE_PORT% %VPS_USER%@%VPS_HOST%
set "SSH_EXIT=%ERRORLEVEL%"
echo [%TIME%] Tunnel stopped - exit %SSH_EXIT% - reconnecting in 5 seconds...
ping -n 6 127.0.0.1 >nul
goto reconnect
