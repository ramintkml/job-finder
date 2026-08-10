import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.database import LinkedInJob
from app.filters.pre_match import evaluate_pre_match
from app.linkedin.cv import resolve_cv_path
from app.linkedin.email_compose import compose_application_email
from app.linkedin.email_send import gmail_configured, send_email
from app.linkedin.job_screen import ai_screen_linkedin_job
from app.linkedin.relevance import (
    ensure_job_relevance_score_async,
    meets_email_relevance_threshold,
    meets_relevance_threshold,
    score_job_relevance_async,
    score_text_relevance_async,
)
from app.linkedin.search import fetch_job_description, search_linkedin_jobs
from app.linkedin.settings import LinkedInSettings, load_linkedin_settings

NO_RECRUITER_EMAIL_REASON = (
    "No recruiter email in job posting — apply on LinkedIn or use the draft email posted to Telegram"
)
NO_RECRUITER_CHANNEL_NOTE = " · Draft email posted to Telegram channel"

logger = logging.getLogger(__name__)


def _job_already_notified_no_recipient(job: LinkedInJob) -> bool:
    return NO_RECRUITER_CHANNEL_NOTE.strip() in (job.match_reason or "")


async def _handle_no_recipient_job(
    db: Session,
    job: LinkedInJob,
    subject: str,
    body: str,
) -> None:
    """Save composed draft and post to the LinkedIn Telegram channel when no hiring email exists."""
    job.email_subject = subject
    job.email_body = body
    job.recipient_email = None
    job.status = "skipped"
    job.error_message = None
    if not _job_already_notified_no_recipient(job):
        reason = (job.match_reason or "").strip()
        job.match_reason = f"{reason}{NO_RECRUITER_CHANNEL_NOTE}" if reason else NO_RECRUITER_EMAIL_REASON + NO_RECRUITER_CHANNEL_NOTE
        db.commit()
        try:
            from app.telegram.service import telegram_service

            await telegram_service.notify_linkedin_job_no_recipient(job)
        except Exception:
            logger.exception("LinkedIn Telegram no-recipient notification failed for job %s", job.id)
    else:
        db.commit()


def _is_own_address(cfg: LinkedInSettings, email: str) -> bool:
    from app.linkedin.email_compose import _applicant_emails

    return email.strip().lower() in _applicant_emails(cfg)


def _evaluate_linkedin_job(text: str, db: Session) -> tuple[bool, str]:
    """Apply pre-match word filters (block phrases, language, etc.)."""
    pre_ok, pre_reason = evaluate_pre_match(text, db=db)
    if not pre_ok:
        return False, f"Pre-match: {pre_reason}"
    return True, ""


def _emails_sent_today(db: Session) -> int:
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        db.query(LinkedInJob)
        .filter(
            LinkedInJob.status == "emailed",
            LinkedInJob.emailed_at.isnot(None),
            LinkedInJob.emailed_at >= start,
        )
        .count()
    )


def _job_data(job: LinkedInJob) -> dict:
    return {
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "job_url": job.job_url,
        "description": job.description,
    }


async def _ai_screen_or_skip(db: Session, job: LinkedInJob, cfg: LinkedInSettings) -> bool:
    """Return True if the job passed AI relevance screening and may be emailed."""
    try:
        screen = await ai_screen_linkedin_job(_job_data(job), cfg)
    except Exception as exc:
        logger.exception("LinkedIn AI screening failed for job %s", job.id)
        job.status = "failed"
        job.error_message = f"AI screening failed: {exc}"
        db.commit()
        return False

    if screen.action == "skip":
        job.status = "skipped"
        job.match_reason = f"AI screening: {screen.skip_reason or 'Not relevant'}"
        job.error_message = None
        db.commit()
        return False

    if screen.review_reason:
        note = f" · AI: {screen.review_reason}"
        if note not in (job.match_reason or ""):
            job.match_reason = (job.match_reason or "") + note
            db.commit()
    return True


async def prepare_matched_job(db: Session, job: LinkedInJob, cfg: LinkedInSettings) -> None:
    """Compose email from template + AI placeholder fills; mark job ready to send (draft)."""
    try:
        subject, body, recipient = compose_application_email(_job_data(job), cfg)
        if not recipient:
            await _handle_no_recipient_job(db, job, subject, body)
            return
        job.email_subject = subject
        job.email_body = body
        job.recipient_email = recipient
        job.relevance_score = await score_job_relevance_async(job)
        job.status = "draft"
        job.error_message = None
        note = " · Email prepared — review and use Start mailing"
        if cfg.test_mode:
            note = " · Test mode — email prepared, will not send until test mode is off"
        if note not in (job.match_reason or ""):
            job.match_reason = (job.match_reason or "") + note
        db.commit()
    except Exception as exc:
        logger.exception("LinkedIn email prepare failed for job %s", job.id)
        job.status = "failed"
        job.error_message = str(exc)
        db.commit()


async def send_prepared_job(
    db: Session,
    job: LinkedInJob,
    cfg: LinkedInSettings,
    *,
    ignore_test_mode: bool = False,
    skip_ai_screen: bool = False,
) -> None:
    """Send a job that already has a composed email."""
    if not skip_ai_screen:
        if not await _ai_screen_or_skip(db, job, cfg):
            return

    if not job.email_body or not job.email_subject:
        await prepare_matched_job(db, job, cfg)
        db.refresh(job)
        if job.status in ("failed", "skipped"):
            return

    if cfg.test_mode and not ignore_test_mode:
        job.status = "draft"
        job.error_message = None
        if "Test mode" not in (job.match_reason or ""):
            job.match_reason = (job.match_reason or "") + " · Test mode — email not sent"
        db.commit()
        return

    if not gmail_configured(cfg):
        job.error_message = "Gmail not configured"
        db.commit()
        return

    to_addr = (job.recipient_email or "").strip()
    if not to_addr:
        if job.email_subject and job.email_body:
            if not _job_already_notified_no_recipient(job):
                await _handle_no_recipient_job(db, job, job.email_subject, job.email_body)
            else:
                job.status = "skipped"
                job.error_message = None
                db.commit()
            return
        job.status = "skipped"
        job.match_reason = NO_RECRUITER_EMAIL_REASON
        job.error_message = None
        db.commit()
        return

    if _is_own_address(cfg, to_addr):
        job.status = "skipped"
        job.match_reason = "Recipient is your own email — not sent (need recruiter address from job posting)"
        job.error_message = None
        db.commit()
        return

    try:
        send_email(
            cfg,
            to_email=to_addr,
            subject=job.email_subject,
            body=job.email_body,
            cv_path=str(resolved) if (resolved := resolve_cv_path(cfg)) else None,
        )
        job.status = "emailed"
        job.emailed_at = datetime.now(timezone.utc)
        job.error_message = None
        job.recipient_email = to_addr
        db.commit()
        try:
            from app.telegram.service import telegram_service

            await telegram_service.notify_linkedin_email_sent(job)
        except Exception:
            logger.exception("LinkedIn Telegram notification failed for job %s", job.id)
    except Exception as exc:
        logger.exception("LinkedIn email send failed for job %s", job.id)
        job.status = "failed"
        job.error_message = str(exc)
        db.commit()


async def process_matched_job(db: Session, job: LinkedInJob, cfg: LinkedInSettings) -> None:
    """Prepare then send in one step (used for single-job send from UI)."""
    score = await ensure_job_relevance_score_async(job, db) if job.relevance_score is None else job.relevance_score
    rel_ok, rel_reason = meets_email_relevance_threshold(
        score,
        threshold=cfg.email_cv_match_threshold,
    )
    if not rel_ok:
        job.status = "skipped"
        job.match_reason = rel_reason
        job.error_message = None
        db.commit()
        return

    if not await _ai_screen_or_skip(db, job, cfg):
        return

    if not job.email_body:
        await prepare_matched_job(db, job, cfg)
        db.refresh(job)
    if job.status == "failed":
        return
    await send_prepared_job(db, job, cfg, ignore_test_mode=True, skip_ai_screen=True)


async def run_linkedin_find(db: Session) -> dict:
    """Step 1: search LinkedIn and list matches — no AI, no sending."""
    cfg = load_linkedin_settings(db)
    if not cfg.enabled:
        return {"ok": True, "skipped": True, "reason": "LinkedIn search disabled"}

    scraped = 0
    found = 0
    matched = 0
    skipped_relevance = 0

    for phrase in cfg.search_phrases:
        phrase = phrase.strip()
        if not phrase:
            continue
        try:
            results = await search_linkedin_jobs(
                phrase,
                location=cfg.location,
                limit=15,
            )
        except Exception as exc:
            logger.exception("LinkedIn search failed for %r", phrase)
            return {"ok": False, "error": str(exc), "phrase": phrase}

        scraped += len(results)

        for item in results:
            existing = (
                db.query(LinkedInJob)
                .filter_by(linkedin_job_id=item["linkedin_job_id"])
                .first()
            )
            if existing:
                continue

            description = item.get("description") or ""
            if not description:
                try:
                    description = await fetch_job_description(item["linkedin_job_id"])
                except Exception:
                    logger.warning("Could not fetch description for job %s", item["linkedin_job_id"])

            blob = f"{item['title']} {item['company']} {description}"
            accepted, skip_reason = _evaluate_linkedin_job(blob, db)
            if not accepted:
                job = LinkedInJob(
                    linkedin_job_id=item["linkedin_job_id"],
                    title=item["title"],
                    company=item["company"],
                    location=item["location"],
                    job_url=item["job_url"],
                    description=description[:8000],
                    status="skipped",
                    match_reason=f"{skip_reason} (search: {phrase})",
                    search_phrase=phrase,
                )
                db.add(job)
                db.commit()
                found += 1
                continue

            score = await score_text_relevance_async(blob)
            rel_ok, rel_reason = meets_relevance_threshold(
                score,
                threshold=cfg.list_cv_match_threshold,
            )
            if not rel_ok:
                job = LinkedInJob(
                    linkedin_job_id=item["linkedin_job_id"],
                    title=item["title"],
                    company=item["company"],
                    location=item["location"],
                    job_url=item["job_url"],
                    description=description[:8000],
                    status="skipped",
                    match_reason=f"{rel_reason} (search: {phrase})",
                    search_phrase=phrase,
                    relevance_score=score,
                )
                db.add(job)
                db.commit()
                found += 1
                skipped_relevance += 1
                continue

            job = LinkedInJob(
                linkedin_job_id=item["linkedin_job_id"],
                title=item["title"],
                company=item["company"],
                location=item["location"],
                job_url=item["job_url"],
                description=description[:8000],
                status="matched",
                match_reason=f"CV match {score}% (search: {phrase})",
                search_phrase=phrase,
                relevance_score=score,
            )
            db.add(job)
            db.commit()
            db.refresh(job)
            found += 1
            matched += 1
            try:
                from app.telegram.service import telegram_service

                await telegram_service.notify_linkedin_job_review(job.id)
            except Exception:
                logger.exception("LinkedIn channel review notify failed for job %s", job.id)

            ats_threshold = getattr(cfg, "ats_resume_threshold", 75) or 75
            if score is not None and score >= ats_threshold:
                try:
                    from app.ats.service import enqueue_for_job

                    enqueue_for_job(job.id, force=False, repost=True)
                except Exception:
                    logger.exception("ATS enqueue failed for job %s", job.id)

    try:
        from app.telegram.service import telegram_service

        backfilled = await telegram_service.renotify_pending_linkedin_jobs()
        if backfilled.get("sent"):
            logger.info("LinkedIn find backfilled %s channel notification(s)", backfilled["sent"])
    except Exception:
        logger.exception("LinkedIn channel backfill after find failed")

    return {
        "ok": True,
        "scraped": scraped,
        "found": found,
        "matched": matched,
        "skipped_relevance": skipped_relevance,
        "list_cv_match_threshold": cfg.list_cv_match_threshold,
    }


async def compose_linkedin_draft(db: Session, job: LinkedInJob, cfg: LinkedInSettings) -> None:
    """AI-compose application email and save as draft (does not send)."""
    subject, body, recipient = compose_application_email(_job_data(job), cfg)
    job.email_subject = subject
    job.email_body = body
    job.recipient_email = recipient or None
    job.status = "draft"
    job.error_message = None
    note = " · Email draft ready"
    if note not in (job.match_reason or ""):
        job.match_reason = (job.match_reason or "") + note
    db.commit()


async def run_linkedin_send_batch(db: Session) -> dict:
    """Step 2: AI-compose (if needed) and send matched / draft jobs."""
    cfg = load_linkedin_settings(db)

    if cfg.test_mode:
        return {
            "ok": True,
            "skipped": True,
            "reason": "Test mode is on — turn off test mode in Settings → LinkedIn to send emails",
        }

    if not gmail_configured(cfg):
        return {"ok": False, "error": "Gmail not configured — set address and App Password in Settings → LinkedIn"}

    jobs = (
        db.query(LinkedInJob)
        .filter(LinkedInJob.status == "draft")
        .order_by(LinkedInJob.created_at.asc())
        .all()
    )

    sent = 0
    failed = 0
    skipped_limit = 0
    skipped_relevance = 0
    skipped_ai = 0
    skipped_no_recipient = 0

    for job in jobs:
        score = await ensure_job_relevance_score_async(job, db) if job.relevance_score is None else job.relevance_score
        rel_ok, rel_reason = meets_email_relevance_threshold(
            score,
            threshold=cfg.email_cv_match_threshold,
        )
        if not rel_ok:
            job.status = "skipped"
            job.match_reason = rel_reason
            db.commit()
            skipped_relevance += 1
            continue

        if _emails_sent_today(db) + sent >= cfg.max_emails_per_day:
            skipped_limit += 1
            continue

        await send_prepared_job(db, job, cfg, ignore_test_mode=True)
        db.refresh(job)
        if job.status == "emailed":
            sent += 1
        elif job.status == "failed":
            failed += 1
        elif job.status == "skipped" and (job.match_reason or "").startswith("AI screening:"):
            skipped_ai += 1
        elif job.status == "skipped" and (
            "recruiter email" in (job.match_reason or "").lower()
            or NO_RECRUITER_CHANNEL_NOTE.strip() in (job.match_reason or "")
        ):
            skipped_no_recipient += 1

    return {
        "ok": True,
        "queued": len(jobs),
        "sent": sent,
        "failed": failed,
        "skipped_limit": skipped_limit,
        "skipped_relevance": skipped_relevance,
        "skipped_ai": skipped_ai,
        "skipped_no_recipient": skipped_no_recipient,
        "email_cv_match_threshold": cfg.email_cv_match_threshold,
    }


# Backward-compatible alias for poller / old route name
async def run_linkedin_search(db: Session) -> dict:
    return await run_linkedin_find(db)
