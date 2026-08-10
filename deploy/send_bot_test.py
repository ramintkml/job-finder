"""One-shot test message to the review chat (no long-poll)."""
from __future__ import annotations

import asyncio

import httpx
from dotenv import dotenv_values

from app.telegram.keyboards import linkedin_job_keyboard, project_review_keyboard


async def main() -> None:
    env = dotenv_values(".env")
    token = (env.get("TELEGRAM_REVIEW_BOT_TOKEN") or "").strip()
    chat_id = (env.get("TELEGRAM_REVIEW_CHAT_ID") or "").strip()
    if not token or not chat_id:
        raise SystemExit("missing TELEGRAM_REVIEW_BOT_TOKEN or TELEGRAM_REVIEW_CHAT_ID")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    tests = [
        (
            "<b>Test Job Found</b>\nIf you see buttons, the review bot works.",
            linkedin_job_keyboard(999001),
        ),
        (
            "<b>Test Freelancer Review</b>\nSend bid / Skip test.",
            project_review_keyboard(999002, api_source=True),
        ),
    ]
    async with httpx.AsyncClient(timeout=30) as client:
        for text, markup in tests:
            r = await client.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "reply_markup": markup,
                },
            )
            data = r.json()
            label = text.split("\n", 1)[0]
            detail = data.get("description") or (data.get("result") or {}).get("message_id")
            print(f"{label} -> ok={data.get('ok')} {detail}")


if __name__ == "__main__":
    asyncio.run(main())
