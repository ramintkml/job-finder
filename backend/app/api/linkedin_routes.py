from dataclasses import asdict
from urllib.parse import quote

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.config import settings
from app.database import LinkedInJob, get_db
from app.linkedin import client as li_client
from app.linkedin import oauth as li_oauth
from app.linkedin import token_store as li_token_store
from app.linkedin.email_compose import compose_sample_application_email, SAMPLE_LINKEDIN_JOB
from app.linkedin.email_send import gmail_configured, send_test_email, test_connection
from app.linkedin.profile_sync import apply_linkedin_identity, sync_profile_to_settings
from app.linkedin.relevance import ensure_job_relevance_score_async
from app.linkedin.service import (
    process_matched_job,
    run_linkedin_find,
    run_linkedin_send_batch,
)
from app.linkedin.settings import LinkedInSettings, load_linkedin_settings, save_linkedin_settings

router = APIRouter(prefix="/linkedin", tags=["linkedin"])
logger = logging.getLogger(__name__)


class LinkedInSettingsUpdate(BaseModel):
    model_config = {"extra": "ignore"}

    enabled: bool = False
    search_phrases: list[str] = []
    trigger_phrases: list[str] = []
    location: str = ""
    poll_interval_minutes: int = 60
    max_emails_per_day: int = 10
    test_mode: bool = True
    auto_mailing_enabled: bool = False
    list_cv_match_threshold: int = Field(default=65, ge=0, le=100)
    email_cv_match_threshold: int = Field(default=70, ge=0, le=100)
    ats_resume_threshold: int = Field(default=75, ge=0, le=100)
    applicant_name: str = ""
    applicant_role: str = ""
    linkedin_email: str = ""
    top_skills: str = ""
    experience_summary: str = ""
    cv_text: str = ""
    cv_file_path: str = ""
    gmail_address: str = ""
    gmail_app_password: str = ""
    from_email: str = ""
    from_name: str = ""
    notification_email: str = ""
    default_recipient_email: str = ""
    email_template: str = ""

    @model_validator(mode="before")
    @classmethod
    def normalize_nulls(cls, data):
        if not isinstance(data, dict):
            return data
        cleaned = dict(data)
        list_fields = {"search_phrases", "trigger_phrases"}
        int_fields = {
            "poll_interval_minutes",
            "max_emails_per_day",
            "list_cv_match_threshold",
            "email_cv_match_threshold",
            "ats_resume_threshold",
        }
        bool_fields = {"enabled", "test_mode", "auto_mailing_enabled"}
        for key, value in list(cleaned.items()):
            if value is not None:
                continue
            if key in list_fields:
                cleaned[key] = []
            elif key in int_fields or key in bool_fields:
                cleaned.pop(key, None)
            else:
                cleaned[key] = ""
        return cleaned


class GmailTestConnection(BaseModel):
    gmail_address: str = ""
    gmail_app_password: str = ""


def _redirect_settings(query: str) -> RedirectResponse:
    return RedirectResponse(url=f"{settings.app_base_url}/?{query}")


def _redirect_error(detail: str) -> RedirectResponse:
    return _redirect_settings(f"view=settings&tab=linkedin&linkedin=error&detail={quote(detail)}")


def _settings_response(cfg: LinkedInSettings, db: Session) -> dict:
    from app.telegram.service import telegram_service

    data = asdict(cfg)
    data["gmail_app_password_set"] = bool(cfg.gmail_app_password)
    data["gmail_app_password"] = ""
    data["gmail_connected"] = gmail_configured(cfg)
    data["linkedin_channel_configured"] = bool(
        settings.telegram_linkedin_channel_id.strip()
    ) or telegram_service.uses_review_bot()
    data.update(
        li_token_store.status_payload(
            db,
            client_configured=settings.linkedin_client_configured,
        )
    )
    return {"settings": data}


def _job_dict(job: LinkedInJob) -> dict:
    return {
        "id": job.id,
        "linkedin_job_id": job.linkedin_job_id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "job_url": job.job_url,
        "description": job.description,
        "search_phrase": job.search_phrase,
        "status": job.status,
        "match_reason": job.match_reason,
        "email_subject": job.email_subject,
        "email_body": job.email_body,
        "recipient_email": job.recipient_email,
        "relevance_score": job.relevance_score,
        "error_message": job.error_message,
        "channel_notified": bool(job.review_channel_message_id and job.review_notified_at),
        "review_notified_at": job.review_notified_at.isoformat() if job.review_notified_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "emailed_at": job.emailed_at.isoformat() if job.emailed_at else None,
    }


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)):
    cfg = load_linkedin_settings(db)
    return _settings_response(cfg, db)


@router.get("/status")
def linkedin_status(db: Session = Depends(get_db)):
    return li_token_store.status_payload(
        db,
        client_configured=settings.linkedin_client_configured,
    )


@router.get("/connect")
def linkedin_connect():
    if not settings.linkedin_client_configured:
        raise HTTPException(
            400,
            "Add LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET to backend/.env, then restart the server.",
        )
    state = li_oauth.create_state()
    url = li_client.build_authorize_url(state=state)
    return RedirectResponse(url=url)


@router.get("/callback")
async def linkedin_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    if error:
        return _redirect_error(error)
    if not code or not li_oauth.validate_state(state):
        return _redirect_settings("view=settings&tab=linkedin&linkedin=error&detail=invalid_oauth_state")

    try:
        tokens = await li_client.exchange_code_for_tokens(code)
        access_token = tokens["access_token"]
        refresh_token = tokens.get("refresh_token", "")
        if not refresh_token:
            logger.warning(
                "LinkedIn OAuth connected without refresh_token — reconnect may be required when access expires"
            )
        userinfo = await li_client.get_userinfo(access_token)
        member_id = str(userinfo.get("sub", ""))
        name = userinfo.get("name") or ""
        email = userinfo.get("email") or ""
        picture = userinfo.get("picture") or ""
        li_token_store.save_tokens(
            db,
            access_token=access_token,
            refresh_token=refresh_token,
            member_id=member_id,
            name=name,
            email=email,
            picture=picture,
        )
        sync_profile_to_settings(db, userinfo)
        return _redirect_settings("view=settings&tab=linkedin&linkedin=connected")
    except li_client.LinkedInApiError as exc:
        return _redirect_error(str(exc))
    except Exception as exc:
        return _redirect_error(str(exc))


@router.post("/disconnect")
def linkedin_disconnect(db: Session = Depends(get_db)):
    li_token_store.clear_tokens(db)
    return {"ok": True}


@router.post("/sync-profile")
async def linkedin_sync_profile(db: Session = Depends(get_db)):
    if not li_token_store.is_connected(db):
        raise HTTPException(400, "LinkedIn is not connected. Click Connect first.")

    tokens = li_token_store.load_tokens(db)
    access_token = tokens.get("linkedin_access_token", "").strip()
    if not access_token:
        raise HTTPException(400, "LinkedIn access token missing. Connect again.")

    try:
        userinfo = await li_client.get_userinfo(access_token)
    except li_client.LinkedInApiError as exc:
        raise HTTPException(400, str(exc)) from exc

    member_id = str(userinfo.get("sub", ""))
    li_token_store.save_profile_snapshot(
        db,
        member_id=member_id,
        name=userinfo.get("name") or "",
        email=userinfo.get("email") or "",
        picture=userinfo.get("picture") or "",
    )
    cfg = sync_profile_to_settings(db, userinfo)
    return _settings_response(cfg, db)


def _merge_settings(db: Session, body: LinkedInSettingsUpdate) -> LinkedInSettings:
    current = load_linkedin_settings(db)
    payload = body.model_dump(exclude_unset=True)
    password = payload.pop("gmail_app_password", None)
    if password is None:
        payload["gmail_app_password"] = current.gmail_app_password
    elif not password and current.gmail_app_password:
        payload["gmail_app_password"] = current.gmail_app_password
    else:
        payload["gmail_app_password"] = str(password).strip().replace(" ", "")
    if payload.get("gmail_address"):
        payload["from_email"] = payload["gmail_address"]
    elif "gmail_address" not in payload and current.gmail_address:
        payload["from_email"] = current.gmail_address
    base = asdict(current)
    base.update(payload)
    cfg = LinkedInSettings(**base)
    return apply_linkedin_identity(db, cfg)


@router.put("/settings")
def update_settings(body: LinkedInSettingsUpdate, db: Session = Depends(get_db)):
    cfg = _merge_settings(db, body)
    save_linkedin_settings(db, cfg)
    return _settings_response(cfg, db)


@router.post("/email/test-compose")
def test_compose_email(body: LinkedInSettingsUpdate, db: Session = Depends(get_db)):
    """Generate a sample application email with AI (does not send)."""
    cfg = _merge_settings(db, body)
    try:
        subject, email_body, recipient = compose_sample_application_email(cfg)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "ok": True,
        "subject": subject,
        "body": email_body,
        "recipient_email": recipient,
        "sample_job": SAMPLE_LINKEDIN_JOB,
        "provider": settings.proposal_provider,
        "model": settings.proposal_model(),
    }


@router.post("/gmail/test-connection")
def gmail_test_connection(body: GmailTestConnection, db: Session = Depends(get_db)):
    cfg = load_linkedin_settings(db)
    sender = body.gmail_address.strip() or cfg.gmail_address.strip()
    pwd = body.gmail_app_password.strip().replace(" ", "") or cfg.gmail_app_password
    ok, reason = test_connection(sender, pwd)
    if not ok:
        raise HTTPException(400, reason)
    return {"ok": True}


@router.post("/gmail/test")
def gmail_test(db: Session = Depends(get_db)):
    cfg = load_linkedin_settings(db)
    if not gmail_configured(cfg):
        raise HTTPException(400, "Save your Gmail address and App Password first")
    try:
        to_addr = send_test_email(cfg)
        return {"ok": True, "to": to_addr}
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/jobs")
async def list_jobs(
    status: str | None = None,
    sort: str = "latest",
    db: Session = Depends(get_db),
):
    q = db.query(LinkedInJob)
    if status == "channel":
        q = q.filter(
            LinkedInJob.review_channel_message_id.isnot(None),
            LinkedInJob.review_notified_at.isnot(None),
        )
    elif status:
        q = q.filter(LinkedInJob.status == status)
    jobs = q.limit(200).all()

    if sort == "relevance":
        for job in jobs:
            await ensure_job_relevance_score_async(job, db)
        jobs.sort(
            key=lambda j: (
                j.relevance_score is None,
                -(j.relevance_score or 0),
                -(j.created_at.timestamp() if j.created_at else 0),
            ),
        )
    else:
        jobs.sort(key=lambda j: -(j.created_at.timestamp() if j.created_at else 0))

    return [_job_dict(j) for j in jobs]


@router.get("/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(LinkedInJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return _job_dict(job)


@router.post("/find")
async def find_jobs(db: Session = Depends(get_db)):
    """Step 1: search and list matches (no AI)."""
    return await run_linkedin_find(db)


@router.post("/send-all")
async def send_all_jobs(db: Session = Depends(get_db)):
    """Step 2: send all prepared draft emails."""
    return await run_linkedin_send_batch(db)


@router.post("/search")
async def search_now(db: Session = Depends(get_db)):
    """Alias for find — search and prepare only."""
    return await run_linkedin_find(db)


@router.post("/jobs/{job_id}/send")
async def send_job_email(job_id: int, db: Session = Depends(get_db)):
    job = db.get(LinkedInJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    cfg = load_linkedin_settings(db)
    cfg.test_mode = False
    job.status = "matched"
    await process_matched_job(db, job, cfg)
    db.refresh(job)
    return _job_dict(job)


@router.delete("/jobs/{job_id}")
def remove_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(LinkedInJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    db.delete(job)
    db.commit()
    return {"ok": True}


@router.post("/jobs/{job_id}/skip")
def skip_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(LinkedInJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    job.status = "skipped"
    job.match_reason = "Skipped manually"
    db.commit()
    return _job_dict(job)


@router.post("/channel/test")
async def linkedin_channel_test():
    from app.telegram.service import telegram_service

    result = await telegram_service.test_linkedin_channel_notifications()
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Channel test failed"))
    return result


@router.post("/channel/renotify")
async def linkedin_channel_renotify(resend: bool = False):
    """Post Job Found messages for matched jobs that never reached the review bot / channel."""
    from app.telegram.service import telegram_service

    if not telegram_service.uses_review_bot() and not settings.telegram_linkedin_channel_id.strip():
        raise HTTPException(
            400,
            "Configure TELEGRAM_REVIEW_BOT_TOKEN + CHAT_ID (or TELEGRAM_LINKEDIN_CHANNEL_ID).",
        )
    if not telegram_service.uses_review_bot() and not telegram_service.connected:
        raise HTTPException(400, "Telegram not connected — log in via Settings first.")

    result = await telegram_service.renotify_pending_linkedin_jobs(force=True, resend_all=resend)
    if result.get("error"):
        raise HTTPException(400, result["error"])
    if result.get("pending", 0) > 0 and result.get("sent", 0) == 0:
        raise HTTPException(
            400,
            f"Could not post Job Found messages ({result['pending']} job(s) waiting). "
            "Check review bot token/chat id, or Telegram channel access.",
        )

    sent = result.get("sent", 0)
    pending = result.get("pending", 0)
    failed = result.get("failed", 0)
    if sent == 0 and pending == 0:
        message = (
            "No matched jobs to post."
            if resend
            else "All matched jobs are already posted. Use resend to post them again."
        )
    elif resend:
        message = f"Re-posted {sent} Job Found message(s) to the LinkedIn channel."
        if failed:
            message += f" {failed} failed."
    else:
        message = f"Posted {sent} Job Found message(s) to the LinkedIn channel."
        if failed:
            message += f" {failed} failed."

    return {"ok": True, **result, "message": message}
