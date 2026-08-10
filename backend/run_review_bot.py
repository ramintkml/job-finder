"""Lean entrypoint: review bot long-poll + optional FastAPI health on localhost.

Use on small VPS when TELEGRAM_REVIEW_BOT_TOKEN + CHAT_ID are set.
Full Job Tracker features still need uvicorn app.main:app; this script
keeps RAM lower when you only need button callbacks against a shared DB.

For Phase 1 on VPS we usually run the full app via pm2 (ecosystem file).
This module remains available for a bot-only worker later.
"""

from __future__ import annotations

import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("review-bot-worker")


async def main() -> None:
    from app.config import settings
    from app.database import init_db
    from app.telegram.bot import review_bot

    if not settings.telegram_review_bot_token.strip() or not settings.telegram_review_chat_id.strip():
        raise SystemExit(
            "Set TELEGRAM_REVIEW_BOT_TOKEN and TELEGRAM_REVIEW_CHAT_ID in backend/.env"
        )

    init_db()
    await review_bot.start()
    logger.info("Review bot worker running — Ctrl+C to stop")
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await review_bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
