"""Background loop — warn review bot when RAM/CPU are overloaded."""

from __future__ import annotations

import asyncio
import logging
import time

from app.config import settings
from app.system.monitor import format_alert, format_status, take_snapshot

logger = logging.getLogger(__name__)

_last_alert_at: dict[str, float] = {}


async def system_alert_loop() -> None:
    """Poll host resources and notify Telegram review bot on overload."""
    # Let the review bot start first.
    await asyncio.sleep(20)
    while True:
        try:
            if settings.system_alerts_enabled:
                await _check_once()
        except Exception:
            logger.exception("System alert loop error")
        interval = max(15, int(settings.system_alert_interval_seconds))
        await asyncio.sleep(interval)


async def build_resource_message(*, force_full: bool = False) -> tuple[str, bool, bool]:
    """Return (html_text, cpu_over, ram_over). force_full always shows both sections."""
    cpu_th = float(settings.system_alert_cpu_percent)
    ram_th = float(settings.system_alert_ram_percent)
    snap = await asyncio.to_thread(
        take_snapshot,
        cpu_sample_seconds=0.8,
        top_n=5,
    )
    cpu_over = snap.cpu_percent >= cpu_th
    ram_over = snap.ram_percent >= ram_th
    if force_full:
        title = "⚠️ <b>هشدار منابع</b>" if (cpu_over or ram_over) else "✅ <b>منابع مناسب</b>"
        text = format_status(
            snap,
            cpu_threshold=cpu_th,
            ram_threshold=ram_th,
            title=title,
        )
    else:
        text = format_alert(
            snap,
            cpu_over=cpu_over,
            ram_over=ram_over,
            cpu_threshold=cpu_th,
            ram_threshold=ram_th,
        )
    return text, cpu_over, ram_over


async def retest_resources() -> dict:
    """Callback handler for Retest button — fresh snapshot + keep keyboard."""
    from app.telegram.keyboards import resource_alert_keyboard

    text, cpu_over, ram_over = await build_resource_message(force_full=True)
    toast = "هنوز بیش از حد است" if (cpu_over or ram_over) else "زیر حد مجاز"
    return {
        "toast": toast,
        "edit_text": text,
        "reply_markup": resource_alert_keyboard(),
    }


async def _check_once() -> None:
    from app.telegram.bot import review_bot
    from app.telegram.keyboards import resource_alert_keyboard

    if not review_bot.admin_configured:
        return

    text, cpu_over, ram_over = await build_resource_message(force_full=False)
    if not cpu_over and not ram_over:
        return

    cooldown = max(60, int(settings.system_alert_cooldown_seconds))
    now = time.monotonic()
    keys: list[str] = []
    if ram_over:
        keys.append("ram")
    if cpu_over:
        keys.append("cpu")

    due = [k for k in keys if now - _last_alert_at.get(k, 0.0) >= cooldown]
    if not due:
        logger.debug(
            "Resource overload suppressed by cooldown (cpu/ram over)",
        )
        return

    # Rebuild alert text only for due resources
    cpu_th = float(settings.system_alert_cpu_percent)
    ram_th = float(settings.system_alert_ram_percent)
    snap = await asyncio.to_thread(take_snapshot, cpu_sample_seconds=0.3, top_n=5)
    text = format_alert(
        snap,
        cpu_over=cpu_over and "cpu" in due,
        ram_over=ram_over and "ram" in due,
        cpu_threshold=cpu_th,
        ram_threshold=ram_th,
    )
    if "بیشترین مصرف" not in text and "آزاد:" not in text:
        return

    result = await review_bot.send_message(text, reply_markup=resource_alert_keyboard())
    if result:
        for k in due:
            _last_alert_at[k] = now
        logger.warning(
            "Sent resource alert host=%s cpu=%.0f%% ram=%.0f%% free_ram=%.0fMiB",
            snap.host,
            snap.cpu_percent,
            snap.ram_percent,
            snap.ram_free_mb,
        )
