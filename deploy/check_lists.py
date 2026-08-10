#!/usr/bin/env python3
from app.telegram.keyboards import main_reply_keyboard
from app.telegram.lists import (
    build_freelancer_api_list,
    build_freelancer_bot_list,
    build_linkedin_jobs_list,
)

kb = main_reply_keyboard()
print("reply_rows", len(kb["keyboard"]))
for builder in (
    build_freelancer_api_list,
    build_freelancer_bot_list,
    build_linkedin_jobs_list,
):
    text, markup = builder()
    n = len((markup or {}).get("inline_keyboard") or [])
    print(builder.__name__, "items", n, "text", text.split("\n")[0])
