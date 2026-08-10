"""Shared review actions for bot inline buttons (and reusable from Telethon)."""

from __future__ import annotations

import html
import logging

from app.database import AtsResume, LinkedInJob, Project, SessionLocal
from app.services.project_service import SOURCE_FREELANCER_API
from app.telegram.channel_messages import (
    format_bid_success,
    format_review_approved,
)
from app.worker.queue import (
    JOB_ATS_REGENERATE,
    JOB_LINKEDIN_EMAIL,
    JOB_LINKEDIN_RESUME,
    enqueue_work,
    queue_heavy_enabled,
)

logger = logging.getLogger(__name__)


async def dispatch(kind: str, action: str, entity_id: int) -> dict:
    if kind == "p":
        return {
            "toast": "حذف شده",
            "edit_text": "⚠️ پیشنهاد فریلنسر از این محصول حذف شده است.",
        }
    elif kind == "j":
        if action == "c":
            return await linkedin_create_email(entity_id)
        if action == "r":
            return await linkedin_create_resume(entity_id)
        if action == "k":
            return await linkedin_skip(entity_id)
    elif kind == "a":
        if action == "g":
            return await ats_regenerate(entity_id)
    return {"toast": "عملیات نامشخص"}


async def project_send(project_id: int) -> dict:
    from app.telegram.service import telegram_service

    db = SessionLocal()
    try:
        project = db.get(Project, project_id)
        if not project or project.status != "pending_review":
            return {"toast": "Already handled", "edit_text": "⏭ Already handled — no longer pending review."}

        if not telegram_service.can_bid_today(db):
            from app.config import settings

            return {
                "toast": "Daily limit reached",
                "edit_text": (
                    f"⚠️ Daily bid limit reached ({settings.max_bids_per_day}). "
                    f"Cannot send project {project.freelancer_project_id or project.id}."
                ),
            }

        # Bids (Telethon + Freelancer API) always run on the VPS — Telegram stays here.
        is_api = getattr(project, "source", None) == SOURCE_FREELANCER_API
        if is_api:
            return await _api_project_send(db, project)
        return await _bot_project_send(db, project)
    finally:
        db.close()


async def _bot_project_send(db, project: Project) -> dict:
    from app.services.project_service import approve_project_for_bid
    from app.telegram.service import telegram_service

    project_id = project.id
    try:
        await approve_project_for_bid(db, project)
    except Exception as exc:
        project.status = "failed"
        project.error_message = f"Proposal generation failed: {exc}"
        db.commit()
        await telegram_service.notify_project_failed(project_id, project.error_message, stage="Proposal generation")
        telegram_service._notify()
        return {
            "toast": "Proposal failed",
            "edit_text": f"❌ Proposal failed for {_code(project)}: {html.escape(str(exc)[:300])}",
        }

    await telegram_service.enqueue_bid(project_id)
    telegram_service._notify()
    return {
        "toast": "Bidding…",
        "edit_text": format_review_approved(project).replace("\n", "\n"),
    }


async def _api_project_send(db, project: Project) -> dict:
    return {
        "toast": "Removed",
        "edit_text": "⚠️ Freelancer API bidding has been removed from LinkedIn Job Finder.",
    }


async def project_skip(project_id: int) -> dict:
    from app.services.project_service import skip_project_review
    from app.telegram.service import telegram_service

    db = SessionLocal()
    try:
        project = db.get(Project, project_id)
        if not project or project.status != "pending_review":
            return {"toast": "Already handled", "edit_text": "⏭ Already handled."}
        skip_project_review(db, project, "Declined via Telegram review bot")
        telegram_service._notify()
        code = html.escape(str(project.freelancer_project_id or project.id))
        return {
            "toast": "Skipped",
            "edit_text": f"⏭ Skipped <code>{code}</code>.",
        }
    finally:
        db.close()


async def linkedin_create_email(job_id: int) -> dict:
    from app.linkedin.service import compose_linkedin_draft
    from app.linkedin.settings import load_linkedin_settings
    from app.telegram.bot import review_bot
    from app.telegram.service import telegram_service

    db = SessionLocal()
    try:
        job = db.get(LinkedInJob, job_id)
        if not job:
            return {"toast": "شغل پیدا نشد"}
        if job.status == "draft" and (job.email_body or "").strip():
            await telegram_service.notify_linkedin_job_draft(job)
            return {
                "toast": "پیش‌نویس آماده است",
                "edit_text": (
                    f"✉ پیش‌نویس ایمیل برای <b>{html.escape(job.title or '')}</b> "
                    "از قبل وجود دارد — دوباره پایین ارسال شد."
                ),
            }
        if job.status not in ("matched", "draft"):
            return {
                "toast": "در دسترس نیست",
                "edit_text": f"⏭ وضعیت شغل {job.status} است — نمی‌توان ایمیل ساخت.",
            }

        if queue_heavy_enabled():
            enqueue_work(db, JOB_LINKEDIN_EMAIL, job_id)
            title = html.escape(job.title or "")
            return {
                "toast": "در صف",
                "edit_text": (
                    f"⏳ ساخت ایمیل در صف است — <b>{title}</b>.\n"
                    "پیش‌نویس اینجا ارسال می‌شود."
                ),
            }

        await review_bot.send_message("⏳ در حال نوشتن ایمیل با هوش مصنوعی…")
        cfg = load_linkedin_settings(db)
        try:
            await compose_linkedin_draft(db, job, cfg)
            db.refresh(job)
        except Exception as exc:
            logger.exception("LinkedIn create draft failed for job %s", job.id)
            job.status = "failed"
            job.error_message = str(exc)
            db.commit()
            await review_bot.send_message(
                f"❌ ساخت ایمیل ناموفق: {html.escape(str(exc)[:400])}"
            )
            return {
                "toast": "ساخت ناموفق",
                "edit_text": f"❌ ساخت ایمیل برای <b>{html.escape(job.title or '')}</b> ناموفق بود.",
            }

        await telegram_service.notify_linkedin_job_draft(job)
        return {
            "toast": "پیش‌نویس ساخته شد",
            "edit_text": f"✉ پیش‌نویس ایمیل برای <b>{html.escape(job.title or '')}</b> ساخته شد.",
        }
    finally:
        db.close()


async def linkedin_create_resume(job_id: int) -> dict:
    from app.ats.service import enqueue_for_job, get_or_create_ats_row
    from app.telegram.bot import review_bot
    from app.telegram.channel_messages import format_linkedin_ats_creating

    db = SessionLocal()
    try:
        job = db.get(LinkedInJob, job_id)
        if not job:
            return {"toast": "شغل پیدا نشد"}
        row = get_or_create_ats_row(db, job.id)
        row.status = "generating"
        row.error_message = None
        db.commit()

        if queue_heavy_enabled():
            enqueue_work(db, JOB_LINKEDIN_RESUME, job.id)
            return {
                "toast": "در صف",
                "edit_text": format_linkedin_ats_creating(job, queued=True),
            }

        enqueue_for_job(job.id, force=True, repost=True)
        creating = format_linkedin_ats_creating(job, queued=False)
        await review_bot.send_message(creating)
        return {
            "toast": "در حال ساخت رزومه…",
            "edit_text": creating,
        }
    finally:
        db.close()


async def linkedin_skip(job_id: int) -> dict:
    db = SessionLocal()
    try:
        job = db.get(LinkedInJob, job_id)
        if not job:
            return {"toast": "شغل پیدا نشد"}
        if job.status == "emailed":
            return {
                "toast": "قبلاً ایمیل شده",
                "edit_text": "⏭ قبلاً ایمیل شده — نمی‌توان رد کرد.",
            }
        job.status = "skipped"
        job.match_reason = (job.match_reason or "") + " · Declined via Telegram review bot"
        job.error_message = None
        db.commit()
        title = html.escape(job.title or "بدون عنوان")
        return {
            "toast": "رد شد",
            "edit_text": f"⏭ <b>{title}</b> رد شد.",
        }
    finally:
        db.close()


async def ats_regenerate(ats_id: int) -> dict:
    from app.ats.service import enqueue_for_job
    from app.telegram.bot import review_bot

    db = SessionLocal()
    try:
        row = db.get(AtsResume, ats_id)
        if not row:
            return {"toast": "رزومه پیدا نشد"}
        job = db.get(LinkedInJob, row.linkedin_job_db_id)
        score = f"{row.total_score}/100" if row.total_score is not None else "—"
        row.status = "generating"
        row.error_message = None
        db.commit()

        if queue_heavy_enabled():
            enqueue_work(db, JOB_ATS_REGENERATE, ats_id)
            title = html.escape((job.title if job else None) or "بدون عنوان")[:80]
            return {
                "toast": "در صف",
                "edit_text": (
                    f"⏳ ساخت مجدد در صف است (امتیاز قبلی {score})\n"
                    f"<b>{title}</b>"
                ),
            }

        enqueue_for_job(row.linkedin_job_db_id, force=True, repost=True)
        title = html.escape((job.title if job else None) or "بدون عنوان")[:80]
        await review_bot.send_message(
            f"🔄 ساخت مجدد رزومه ATS برای <b>{title}</b> "
            f"(امتیاز قبلی {score})… پیام جدید با فایل و امتیاز اینجا می‌آید."
        )
        return {
            "toast": "در حال ساخت مجدد…",
            "edit_text": (
                f"🔄 در حال ساخت مجدد… (امتیاز قبلی {score})\n"
                f"<b>{title}</b>\n"
                "پیام رزومه جدید به‌زودی می‌آید."
            ),
        }
    finally:
        db.close()


def _code(project: Project) -> str:
    return html.escape(project.freelancer_project_id or f"#{project.id}")
