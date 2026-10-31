@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

REM Sync LinkedIn Job Finder to VPS as a SEPARATE app.
REM Does NOT deploy into ~/job-tracker or touch clinic services.

set "SSH_KEY=%USERPROFILE%\.ssh\ot_clinic_deploy"
set "VPS_USER=deploy"
set "VPS_HOST=156.253.5.183"
set "REMOTE=/home/deploy/linkedin-job-finder"

if not exist "%SSH_KEY%" (
  echo ERROR: missing SSH key %SSH_KEY%
  exit /b 1
)

where scp >nul 2>&1
if errorlevel 1 (
  echo ERROR: scp not found
  exit /b 1
)

echo Building authenticated dashboard...
call npm run build --prefix frontend
if errorlevel 1 exit /b 1

echo Creating remote dirs...
ssh -i "%SSH_KEY%" -o IdentitiesOnly=yes %VPS_USER%@%VPS_HOST% "mkdir -p %REMOTE%/backend %REMOTE%/deploy %REMOTE%/logs %REMOTE%/data %REMOTE%/frontend"

echo Uploading backend app (no venv / no .env overwrite)...
scp -i "%SSH_KEY%" -o IdentitiesOnly=yes -r backend\app %VPS_USER%@%VPS_HOST%:%REMOTE%/backend/
scp -i "%SSH_KEY%" -o IdentitiesOnly=yes backend\requirements.txt backend\requirements-vps.txt backend\run_review_bot.py %VPS_USER%@%VPS_HOST%:%REMOTE%/backend/
scp -i "%SSH_KEY%" -o IdentitiesOnly=yes -r deploy\* %VPS_USER%@%VPS_HOST%:%REMOTE%/deploy/
scp -i "%SSH_KEY%" -o IdentitiesOnly=yes AGENT_BRIEF.md README.md %VPS_USER%@%VPS_HOST%:%REMOTE%/

echo Uploading built dashboard...
scp -i "%SSH_KEY%" -o IdentitiesOnly=yes -r frontend\dist %VPS_USER%@%VPS_HOST%:%REMOTE%/frontend/
if errorlevel 1 exit /b 1

echo Running remote setup...
ssh -i "%SSH_KEY%" -o IdentitiesOnly=yes %VPS_USER%@%VPS_HOST% "chmod +x %REMOTE%/deploy/setup_vps.sh && bash %REMOTE%/deploy/setup_vps.sh"

echo.
echo Done. Ensure DASHBOARD_ADMIN_PASSWORD is set on VPS.
echo Restart the PC worker with launch.bat after this protocol upgrade.
echo Edit secrets on VPS if needed:
echo   ssh -i "%SSH_KEY%" %VPS_USER%@%VPS_HOST%
echo   nano %REMOTE%/backend/.env
echo   export PATH=$HOME/.npm-global/bin:$PATH ^&^& pm2 restart linkedin-job-finder
echo.
endlocal
