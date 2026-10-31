#!/usr/bin/env bash
# Forced-command entrypoint for this repository's dedicated deployment SSH key.
set -euo pipefail
umask 077
APP=/home/deploy/linkedin-job-finder
if [[ ! ${SSH_ORIGINAL_COMMAND:-} =~ ^deploy\ ([0-9a-f]{40})$ ]]; then
  echo 'Only deployment of a commit SHA is allowed.' >&2
  exit 2
fi
SHA=${BASH_REMATCH[1]}
mkdir -p "$APP/.deploy/incoming" "$APP/.deploy/releases/$SHA"
ARCHIVE="$APP/.deploy/incoming/$SHA.tgz"
cat > "$ARCHIVE"
python3 - "$ARCHIVE" <<'PY'
import sys,tarfile,pathlib
with tarfile.open(sys.argv[1], 'r:gz') as archive:
    members=archive.getmembers()
    if len(members)>10000 or sum(m.size for m in members)>200_000_000:
        raise SystemExit('Deployment artifact is too large')
    for member in members:
        path=pathlib.PurePosixPath(member.name)
        if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()):
            raise SystemExit('Invalid deployment artifact member')
PY
tar -xzf "$ARCHIVE" --no-same-owner --no-same-permissions -C "$APP/.deploy/releases/$SHA"
[[ $(cat "$APP/.deploy/releases/$SHA/REVISION") == "$SHA" ]]
bash "$APP/.deploy/releases/$SHA/deploy/ci_deploy.sh" "$SHA"
