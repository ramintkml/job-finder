#!/usr/bin/env bash
# Called only by the Actions forced-command entrypoint; never touches other PM2 apps.
set -euo pipefail
umask 077
APP=/home/deploy/linkedin-job-finder
SHA=${1:?Missing revision}
[[ $SHA =~ ^[0-9a-f]{40}$ ]]
RELEASE="$APP/.deploy/releases/$SHA"
[[ -f "$RELEASE/REVISION" && -f "$APP/backend/.env" ]]
[[ $(realpath "$APP/backend") == "$APP/backend" ]]
[[ $(realpath "$APP/data") == "$APP/data" ]]
export PATH="$HOME/.npm-global/bin:$PATH"
exec 9>"$APP/.deploy/deploy.lock"
flock -n 9 || { echo 'Another deployment is active.' >&2; exit 1; }
cd "$APP"
# No active generation may be interrupted by a protocol/schema upgrade.
backend/venv/bin/python - <<'PY'
import pathlib,sqlite3
path=pathlib.Path('data/freelancer.db')
if path.exists():
    with sqlite3.connect(path) as db:
        busy=db.execute("SELECT count(*) FROM work_jobs WHERE status IN ('claimed','applying')").fetchone()[0]
        if busy: raise SystemExit('Worker is busy; retry deployment after active jobs finish.')
PY
# Install dependencies before touching running source. Additive dependency changes
# preserve rollback compatibility with the prior release.
backend/venv/bin/python -m pip install -q -r "$RELEASE/backend/requirements-vps.txt"
# Exercise native imports and the actual exporter on the TARGET CPU too.
# A green CI runner alone cannot detect an older VPS instruction set.
PYTHONPATH="$RELEASE/backend" backend/venv/bin/python -m app.ats.pdf_runtime
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP="$APP/.deploy/backups/${STAMP}_${SHA}.tgz"
mkdir -p "$APP/.deploy/backups"
STOPPED=0
BACKED_UP=0
rollback() {
  result=$?
  trap - ERR
  if [[ $STOPPED == 1 ]]; then
    pm2 stop linkedin-job-finder >/dev/null 2>&1 || true
    if [[ $BACKED_UP == 1 ]]; then
      tar -xzf "$BACKUP" -C "$APP"
    fi
    pm2 startOrReload "$APP/deploy/ecosystem.config.json" --update-env >/dev/null 2>&1 || true
  fi
  echo 'Deployment failed; previous release restored where available.' >&2
  exit "$result"
}
trap rollback ERR
pm2 stop linkedin-job-finder >/dev/null
STOPPED=1
# Stopping the sole API process makes the SQLite + hidden credential-key backup consistent.
tar -czf "$BACKUP" data backend/app backend/.env frontend deploy/ecosystem.config.json
BACKED_UP=1
rsync -a --delete --exclude='__pycache__' "$RELEASE/backend/app/" "$APP/backend/app/"
rsync -a --delete "$RELEASE/frontend/dist/" "$APP/frontend/dist/"
cp "$RELEASE/backend/requirements-vps.txt" "$APP/backend/requirements-vps.txt"
cp "$RELEASE/deploy/ecosystem.config.json" "$APP/deploy/ecosystem.config.json"
cp "$RELEASE/deploy/ci_entrypoint.sh" "$APP/deploy/ci_entrypoint.sh"
cp "$RELEASE/deploy/ci_deploy.sh" "$APP/deploy/ci_deploy.sh"
cp "$RELEASE/README.md" "$RELEASE/AGENT_BRIEF.md" "$APP/"
chmod 700 "$APP/deploy/ci_entrypoint.sh" "$APP/deploy/ci_deploy.sh"
backend/venv/bin/python - "$SHA" <<'PY'
import os,pathlib,secrets,sys
from dotenv import dotenv_values,set_key
path=pathlib.Path('backend/.env')
values=dotenv_values(path)
if not values.get('DASHBOARD_ADMIN_PASSWORD'):
    output=pathlib.Path('data/dashboard-admin-password.txt')
    password=output.read_text().strip() if output.is_file() else secrets.token_urlsafe(32)
    if not output.is_file():
        descriptor=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'w') as stream: stream.write(password+'\n')
    set_key(str(path),'DASHBOARD_ADMIN_PASSWORD',password)
set_key(str(path),'AI_PROVIDER','codex')
set_key(str(path),'CODEX_EXECUTION_MODE','queue')
set_key(str(path),'DEPLOYMENT_REVISION',sys.argv[1])
PY
(cd backend && venv/bin/python -c 'from app.database import init_db; init_db(); from app.main import app; print("import-ok", app.title)')
pm2 startOrReload "$APP/deploy/ecosystem.config.json" --update-env >/dev/null
for attempt in $(seq 1 30); do
  if curl --fail --silent --max-time 3 http://127.0.0.1:8001/api/health > "$APP/.deploy/health.json"; then
    if backend/venv/bin/python - "$SHA" <<'PY'
import json,sys
with open('.deploy/health.json') as stream: health=json.load(stream)
assert health.get('revision')==sys.argv[1], 'Revision mismatch'
assert health.get('ai_engine')=='codex', 'AI engine mismatch'
PY
    then break; fi
  fi
  [[ $attempt != 30 ]]
  sleep 2
done
[[ $(curl --silent --output /dev/null --write-out '%{http_code}' http://127.0.0.1:8001/api/applications) == 401 ]]
curl --fail --silent http://127.0.0.1:8001/ | grep -q 'Career Pilot'
printf '%s\n' "$SHA" > "$APP/.deploy/current_revision"
pm2 save >/dev/null
STOPPED=0
trap - ERR
printf 'Deployed revision %s; health and authentication checks passed.\n' "$SHA"
