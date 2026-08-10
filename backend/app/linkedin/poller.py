"""Poll LinkedIn for jobs and optionally run the full mail pipeline."""

import logging

from app.database import SessionLocal
from app.linkedin.email_send import gmail_configured
from app.linkedin.service import run_linkedin_find, run_linkedin_send_batch
from app.linkedin.settings import load_linkedin_settings
from app.telegram.service import telegram_service

logger = logging.getLogger(__name__)


def _mail_blockers(cfg) -> list[str]:
    blockers: list[str] = []
    if not cfg.auto_mailing_enabled:
        blockers.append("auto mailing disabled in Settings → LinkedIn")
    if cfg.test_mode:
        blockers.append("test mode is on")
    if not telegram_service.automation_enabled:
        blockers.append("automation stopped (click Start on dashboard)")
    if not gmail_configured(cfg):
        blockers.append("Gmail not configured")
    return blockers


async def poll_linkedin_jobs() -> None:
    db = SessionLocal()
    try:
        cfg = load_linkedin_settings(db)
        if not cfg.enabled:
            return
        if not telegram_service.automation_enabled:
            logger.debug("LinkedIn poll skipped — automation paused")
            return

        find_result = await run_linkedin_find(db)
        if find_result.get("ok") and not find_result.get("skipped"):
            logger.info(
                "LinkedIn poll find: found=%s matched=%s skipped_cv=%s",
                find_result.get("found", 0),
                find_result.get("matched", 0),
                find_result.get("skipped_relevance", 0),
            )
        elif find_result.get("error"):
            logger.warning("LinkedIn poll find failed: %s", find_result.get("error"))

        mail_blockers = _mail_blockers(cfg)
        if mail_blockers:
            logger.debug("LinkedIn auto-mail skipped: %s", "; ".join(mail_blockers))
            return

        mail_result = await run_linkedin_send_batch(db)
        if mail_result.get("skipped"):
            logger.debug("LinkedIn auto-mail: %s", mail_result.get("reason"))
            return
        if mail_result.get("ok"):
            sent = mail_result.get("sent", 0)
            skipped_ai = mail_result.get("skipped_ai", 0)
            if sent or skipped_ai or mail_result.get("failed"):
                logger.info(
                    "LinkedIn auto-mail: sent=%s failed=%s skipped_ai=%s skipped_cv=%s",
                    sent,
                    mail_result.get("failed", 0),
                    skipped_ai,
                    mail_result.get("skipped_relevance", 0),
                )
        elif mail_result.get("error"):
            logger.warning("LinkedIn auto-mail failed: %s", mail_result.get("error"))
    except Exception:
        logger.exception("LinkedIn poll error")
    finally:
        db.close()


def linkedin_poll_interval_seconds(db) -> int:
    cfg = load_linkedin_settings(db)
    return max(15, cfg.poll_interval_minutes) * 60
