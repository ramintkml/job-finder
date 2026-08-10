#!/usr/bin/env python3
import json
from pathlib import Path
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:8000/api/settings") as r:
    d = json.load(r)
print("telegram_connected", d.get("telegram_connected"))
print("needs_auth", d.get("telegram_needs_auth"))
print("review_bot", d.get("review_bot_configured"))

vals = {}
for line in Path.home().joinpath("job-tracker/backend/.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        vals[k.strip()] = v.strip().lstrip("\ufeff")

api_id = vals.get("TELEGRAM_API_ID", "")
print("api_id_ok", bool(api_id and api_id not in ("0", "")))
print("hash_len", len(vals.get("TELEGRAM_API_HASH", "")))
print("phone_len", len(vals.get("TELEGRAM_PHONE", "")))
print("session_exists", Path.home().joinpath("job-tracker/data/telegram.session").exists())
