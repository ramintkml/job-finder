#!/usr/bin/env python3
"""Merge TELEGRAM_* into VPS .env from a sibling telegram.env file (KEY=value lines)."""
from __future__ import annotations

import pathlib
import sqlite3

home = pathlib.Path.home() / "job-tracker"
src = home / "deploy" / "telegram.env.snippet"
env_path = home / "backend" / ".env"
if not src.exists():
    raise SystemExit(f"missing {src}")

updates = {}
for line in src.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    updates[k.strip()] = v.strip()

text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
lines = text.splitlines()
out = []
seen = set()
for line in lines:
    if "=" in line and not line.strip().startswith("#"):
        k = line.split("=", 1)[0].strip()
        if k in updates:
            out.append(f"{k}={updates[k]}")
            seen.add(k)
            continue
    out.append(line)
for k, v in updates.items():
    if k not in seen:
        out.append(f"{k}={v}")
env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
print("ENV_TELEGRAM_UPDATED")

db = home / "data" / "freelancer.db"
if db.exists():
    con = sqlite3.connect(db)
    cur = con.execute(
        "UPDATE work_jobs SET status='cancelled', error_message=? "
        "WHERE job_type='project_send_bid' AND status IN ('pending','claimed')",
        ("Bids stay on VPS",),
    )
    con.commit()
    print("CANCELLED", cur.rowcount)
    con.close()

src.unlink(missing_ok=True)
print("SNIPPET_REMOVED")
