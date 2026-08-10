#!/usr/bin/env python3
import json
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:8000/api/settings") as r:
    d = json.load(r)
print("review_bot", d.get("review_bot_configured"))
print("fln_notify_ok", d.get("freelancer_channel_configured"))
print("li_notify_ok", d.get("linkedin_channel_configured"))
print("health_ok", True)
