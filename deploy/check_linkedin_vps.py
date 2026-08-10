#!/usr/bin/env python3
from pathlib import Path
import os
import sys

# Load like the app does
sys.path.insert(0, str(Path.home() / "job-tracker" / "backend"))
os.chdir(Path.home() / "job-tracker" / "backend")

from app.config import settings

print("client_id_len", len(settings.linkedin_client_id or ""))
print("client_secret_len", len(settings.linkedin_client_secret or ""))
print("redirect_uri", settings.linkedin_redirect_uri)
print("configured", settings.linkedin_client_configured)
print("env_file", settings.model_config.get("env_file") if hasattr(settings, "model_config") else "?")

# raw .env keys
vals = {}
p = Path.home() / "job-tracker/backend/.env"
for line in p.read_text(encoding="utf-8-sig").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        vals[k.strip().lstrip("\ufeff")] = v.strip()
for k in ("LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET", "LINKEDIN_REDIRECT_URI"):
    v = vals.get(k, "")
    if "SECRET" in k:
        print(f"file_{k}_len", len(v))
    else:
        print(f"file_{k}", repr(v[:40] if v else ""))
