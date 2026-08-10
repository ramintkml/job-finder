#!/usr/bin/env bash
# Deploy LinkedIn Job Finder to VPS WITHOUT touching:
#   - ot-clinic (website :3000 / API :5000)
#   - clinic-mailer-bot (systemd)
#   - job-tracker (PM2 :8000)
#
# This app uses:
#   path:  /home/deploy/linkedin-job-finder
#   port:  127.0.0.1:8001
#   pm2:   linkedin-job-finder
set -euo pipefail

APP_DIR="${HOME}/linkedin-job-finder"
BACKEND="${APP_DIR}/backend"
LOGS="${APP_DIR}/logs"
export PATH="${HOME}/.npm-global/bin:${PATH}"

mkdir -p "${LOGS}" "${APP_DIR}/data"

cd "${BACKEND}"

if [[ ! -d venv ]]; then
  python3 -m venv venv
fi
# Prefer VPS-light deps if present
REQ=requirements.txt
if [[ -f requirements-vps.txt ]]; then
  REQ=requirements-vps.txt
fi
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -r "${REQ}"

if [[ ! -f .env ]]; then
  if [[ -f ../deploy/vps.env.template ]]; then
    cp ../deploy/vps.env.template .env
    echo "Created ${BACKEND}/.env from template — EDIT TOKEN + PRICES before restart."
  else
    echo "ERROR: missing .env and template"
    exit 1
  fi
fi

# Sanity: refuse to bind 8000 (job-tracker)
if grep -qE '^PORT=8000\s*$' .env 2>/dev/null; then
  echo "ERROR: PORT=8000 would collide with job-tracker. Use PORT=8001."
  exit 1
fi

./venv/bin/python -c "from app.main import app; print('import-ok', app.title)"

pm2 startOrReload "${APP_DIR}/deploy/ecosystem.config.json" --update-env
pm2 save

echo
echo "=== isolation check ==="
pm2 list
systemctl --user is-active clinic-mailer-bot.service || true
systemctl --user is-active ot-clinic-backend.service || true
systemctl --user is-active ot-clinic-frontend.service || true
ss -tln | grep -E ':8000|:8001|:3000|:5000' || true
echo
echo "linkedin-job-finder should be on 127.0.0.1:8001"
echo "job-tracker stays on 127.0.0.1:8000"
