"""One-shot test: send current RAM/CPU snapshot to the review bot."""

from __future__ import annotations

import asyncio

from app.system.alerts import build_resource_message
from app.telegram.bot import review_bot
from app.telegram.keyboards import resource_alert_keyboard


async def main() -> None:
    text, cpu_over, ram_over = await build_resource_message(force_full=True)
    text = "<b>Safety monitor test</b> (tap Retest anytime)\n\n" + text
    if not review_bot.configured:
        raise SystemExit("Review bot not configured")
    await review_bot.start()
    result = await review_bot.send_message(text, reply_markup=resource_alert_keyboard())
    print(f"ok={bool(result)} cpu_over={cpu_over} ram_over={ram_over}")


if __name__ == "__main__":
    asyncio.run(main())
