"""Pending LinkedIn job lists for the review bot reply keyboard (Farsi)."""

from __future__ import annotations

import html
import logging

from app.database import LinkedInJob, SessionLocal
from app.telegram.keyboards import pending_list_keyboard

logger = logging.getLogger(__name__)

LIST_LIMIT = 20

LI_JOBS_LIST_LABELS = {
    "💼 شغل‌های جدید",
    "شغل‌های جدید",
    "💼 لیست شغل‌های لینکدین",
    "لیست شغل‌های لینکدین",
    "/li_jobs_list",
    "/jobs",
}


def _short_title(title: str | None, *, fallback: str) -> str:
    text = (title or "").strip() or fallback
    text = " ".join(text.split())
    if len(text) > 48:
        return text[:45] + "…"
    return text


def build_linkedin_jobs_list() -> tuple[str, dict | None]:
    db = SessionLocal()
    try:
        rows = (
            db.query(LinkedInJob)
            .filter(LinkedInJob.status == "matched")
            .order_by(LinkedInJob.created_at.desc())
            .limit(LIST_LIMIT)
            .all()
        )
    finally:
        db.close()

    if not rows:
        return (
            "💼 <b>شغل‌های جدید</b>\n\n"
            "هنوز شغل منطبقی در صف بررسی نیست.\n"
            "جستجو را از <b>🔍 تنظیم جستجو</b> فعال کنید.",
            None,
        )

    items = []
    for i, job in enumerate(rows, start=1):
        company = (job.company or "").strip()
        title = _short_title(job.title, fallback=f"شغل #{job.id}")
        label = f"{i}. {title}" if not company else f"{i}. {title} · {company[:20]}"
        items.append((label[:64], f"ls:l:{job.id}"))

    text = (
        f"💼 <b>شغل‌های جدید</b>\n"
        f"{len(rows)} شغل منطبق برای بررسی — یکی را لمس کنید:\n\n"
        f"<i>مسیر: مشاهده آگهی → ایمیل/رزومه → یا رد</i>"
    )
    return text, pending_list_keyboard(items)


async def resend_linkedin_review(job_id: int) -> dict:
    from app.telegram.service import telegram_service

    db = SessionLocal()
    try:
        job = db.get(LinkedInJob, job_id)
        if not job:
            return {"toast": "پیدا نشد", "alert": True}
        if job.status != "matched":
            return {
                "toast": f"وضعیت: {job.status}",
                "alert": True,
            }
        title = html.escape(_short_title(job.title, fallback=f"#{job.id}"))
    finally:
        db.close()

    ok = await telegram_service.notify_linkedin_job_review(
        job_id,
        force=True,
        resend=True,
    )
    if ok:
        return {"toast": "باز شد", "follow_note": f"مرور لینکدین دوباره ارسال شد: {title}"}
    return {"toast": "ارسال مجدد ممکن نشد", "alert": True}
