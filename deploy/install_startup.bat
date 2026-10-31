@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_startup.ps1"
exit /b %ERRORLEVEL%
