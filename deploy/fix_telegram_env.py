#!/usr/bin/env python3
"""Fix TELEGRAM_* keys on VPS .env (strip BOM / duplicate lines)."""
from __future__ import annotations

import pathlib
import re
import sys

home = pathlib.Path.home() / "job-tracker"
env_path = home / "backend" / ".env"
if len(sys.argv) < 2:
    raise SystemExit("usage: fix_telegram_env.py <snippet_path>")
src = pathlib.Path(sys.argv[1])
raw = src.read_text(encoding="utf-8-sig")
updates = {}
for line in raw.splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    updates[k.strip().lstrip("\ufeff")] = v.strip()

text = env_path.read_text(encoding="utf-8-sig")
lines = text.splitlines()
out = []
seen = set()
for line in lines:
    if "=" in line and not line.strip().startswith("#"):
        k = line.split("=", 1)[0].strip().lstrip("\ufeff")
        if k in updates:
            if k in seen:
                continue
            out.append(f"{k}={updates[k]}")
            seen.add(k)
            continue
        # drop BOM-prefixed duplicates of telegram keys
        if k.startswith("TELEGRAM_") and k in updates:
            continue
    out.append(line)
for k, v in updates.items():
    if k not in seen:
        out.append(f"{k}={v}")
env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
print("FIXED", sorted(updates))
src.unlink(missing_ok=True)
