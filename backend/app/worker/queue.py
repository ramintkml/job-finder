"""Work queue helpers — enqueue on VPS, claim/complete from PC worker."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.database import AppSettings, AtsResume, LinkedInJob, Project, WorkJob

logger = logging.getLogger(__name__)

JOB_LINKEDIN_EMAIL = "linkedin_create_email"
JOB_LINKEDIN_RESUME = "linkedin_create_resume"
JOB_ATS_REGENERATE = "ats_regenerate"
JOB_PROJECT_SEND = "project_send_bid"
JOB_VECTOR_SCREEN = "vector_screen"
JOB_CODEX_APPLY = "codex_apply"
JOB_SAVE_FILES = "save_files"

ACTIVE_STATUSES = ("pending", "claimed")
CLAIM_STALE_MINUTES = 20
WORKER_ONLINE_SECONDS = 45

HEARTBEAT_AT_KEY = "worker_heartbeat_at"
HEARTBEAT_ID_KEY = "worker_heartbeat_id"
HEARTBEAT_NAME_KEY = "worker_heartbeat_name"
HEARTBEAT_TELETHON_KEY = "worker_telethon_connected"
HEARTBEAT_TELETHON_AUTH_KEY = "worker_telethon_needs_auth"
HEARTBEAT_RAG_CHROMA_KEY = "worker_rag_chroma"


def queue_heavy_enabled() -> bool:
    return bool(settings.queue_heavy_work)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(AppSettings, key)
    if row:
        row.value = value
    else:
        db.add(AppSettings(key=key, value=value))


def _get_setting(db: Session, key: str) -> str:
    row = db.get(AppSettings, key)
    return (row.value if row else "") or ""


def record_heartbeat(
    db: Session,
    worker_id: str,
    name: str = "",
    *,
    telethon_connected: bool | None = None,
    telethon_needs_auth: bool | None = None,
    rag_chroma: bool | None = None,
) -> None:
    _set_setting(db, HEARTBEAT_AT_KEY, _now().isoformat())
    _set_setting(db, HEARTBEAT_ID_KEY, worker_id[:128])
    if name:
        _set_setting(db, HEARTBEAT_NAME_KEY, name[:128])
    if telethon_connected is not None:
        _set_setting(db, HEARTBEAT_TELETHON_KEY, "true" if telethon_connected else "false")
    if telethon_needs_auth is not None:
        _set_setting(db, HEARTBEAT_TELETHON_AUTH_KEY, "true" if telethon_needs_auth else "false")
    if rag_chroma is not None:
        _set_setting(db, HEARTBEAT_RAG_CHROMA_KEY, "true" if rag_chroma else "false")
    db.commit()


def worker_status(db: Session) -> dict[str, Any]:
    at_raw = _get_setting(db, HEARTBEAT_AT_KEY)
    worker_id = _get_setting(db, HEARTBEAT_ID_KEY)
    name = _get_setting(db, HEARTBEAT_NAME_KEY)
    telethon_raw = _get_setting(db, HEARTBEAT_TELETHON_KEY)
    telethon_auth_raw = _get_setting(db, HEARTBEAT_TELETHON_AUTH_KEY)
    rag_chroma_raw = _get_setting(db, HEARTBEAT_RAG_CHROMA_KEY)
    last_seen = None
    online = False
    age_seconds = None
    if at_raw:
        try:
            last_seen = datetime.fromisoformat(at_raw)
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            age_seconds = (_now() - last_seen).total_seconds()
            online = age_seconds <= WORKER_ONLINE_SECONDS
        except ValueError:
            last_seen = None

    pending = db.query(WorkJob).filter(WorkJob.status == "pending").count()
    claimed = db.query(WorkJob).filter(WorkJob.status == "claimed").count()
    failed = (
        db.query(WorkJob)
        .filter(WorkJob.status == "failed")
        .order_by(WorkJob.id.desc())
        .limit(5)
        .count()
    )
    telethon_connected = telethon_raw.lower() in ("1", "true", "yes") if telethon_raw else False
    telethon_needs_auth = telethon_auth_raw.lower() in ("1", "true", "yes") if telethon_auth_raw else False
    rag_chroma = rag_chroma_raw.lower() in ("1", "true", "yes") if rag_chroma_raw else False
    if not online:
        telethon_connected = False
        rag_chroma = False
    return {
        "queue_heavy_work": queue_heavy_enabled(),
        "worker_online": online,
        "worker_id": worker_id or None,
        "worker_name": name or None,
        "last_seen_at": last_seen.isoformat() if last_seen else None,
        "age_seconds": int(age_seconds) if age_seconds is not None else None,
        "pending": pending,
        "claimed": claimed,
        "recent_failed": failed,
        "telethon_connected": telethon_connected,
        "telethon_needs_auth": telethon_needs_auth,
        "worker_rag_chroma": rag_chroma,
    }


def _linkedin_job_payload(job: LinkedInJob) -> dict:
    return {
        "id": job.id,
        "linkedin_job_id": job.linkedin_job_id,
        "title": job.title or "",
        "company": job.company or "",
        "location": job.location or "",
        "job_url": job.job_url or "",
        "description": job.description or "",
        "search_phrase": job.search_phrase or "",
        "status": job.status,
        "match_reason": job.match_reason,
        "relevance_score": job.relevance_score,
        "email_subject": job.email_subject,
        "email_body": job.email_body,
        "recipient_email": job.recipient_email,
    }


def _project_payload(project: Project) -> dict:
    return {
        "id": project.id,
        "freelancer_project_id": project.freelancer_project_id,
        "telegram_message_id": project.telegram_message_id,
        "title": project.title or "",
        "description": project.description or "",
        "raw_message": project.raw_message or "",
        "budget_text": project.budget_text or "",
        "is_hourly": bool(project.is_hourly),
        "currency": project.currency or "USD",
        "status": project.status,
        "proposal": project.proposal,
        "bid_amount": project.bid_amount,
        "bid_duration": project.bid_duration,
        "duration_type": project.duration_type,
        "source": project.source or "telegram_bot",
        "confidence": project.confidence,
        "review_reason": project.review_reason,
    }


def _ats_payload(row: AtsResume) -> dict:
    return {
        "id": row.id,
        "linkedin_job_db_id": row.linkedin_job_db_id,
        "status": row.status,
        "total_score": row.total_score,
        "scores_json": row.scores_json,
        "keyword_matched": row.keyword_matched,
        "keyword_missing": row.keyword_missing,
        "improvement_tips_json": row.improvement_tips_json,
    }


def build_payload(db: Session, job_type: str, entity_id: int, extra: dict | None = None) -> dict:
    payload: dict[str, Any] = {"job_type": job_type, "entity_id": entity_id}
    if extra:
        payload.update(extra)

    if job_type in (JOB_LINKEDIN_EMAIL, JOB_LINKEDIN_RESUME):
        job = db.get(LinkedInJob, entity_id)
        if not job:
            raise ValueError(f"LinkedIn job {entity_id} not found")
        payload["linkedin_job"] = _linkedin_job_payload(job)
        if job_type == JOB_LINKEDIN_EMAIL:
            from app.linkedin.settings import load_linkedin_settings

            payload["linkedin_settings"] = asdict(load_linkedin_settings(db))
        if job_type == JOB_LINKEDIN_RESUME:
            row = db.query(AtsResume).filter(AtsResume.linkedin_job_db_id == entity_id).first()
            if row:
                payload["ats_resume"] = _ats_payload(row)
                payload["ats_id"] = row.id

    elif job_type == JOB_ATS_REGENERATE:
        row = db.get(AtsResume, entity_id)
        if not row:
            raise ValueError(f"ATS resume {entity_id} not found")
        payload["ats_resume"] = _ats_payload(row)
        payload["ats_id"] = row.id
        job = db.get(LinkedInJob, row.linkedin_job_db_id)
        if not job:
            raise ValueError(f"LinkedIn job {row.linkedin_job_db_id} not found")
        payload["linkedin_job"] = _linkedin_job_payload(job)
        payload["force"] = True
        payload["repost"] = True

    elif job_type == JOB_PROJECT_SEND:
        project = db.get(Project, entity_id)
        if not project:
            raise ValueError(f"Project {entity_id} not found")
        payload["project"] = _project_payload(project)
        payload["test_mode"] = settings.test_mode
        payload["freelancer_bidding_enabled"] = settings.freelancer_bidding_enabled
        payload["max_bids_per_day"] = settings.max_bids_per_day

    elif job_type == JOB_VECTOR_SCREEN:
        text = (payload.get("text") or "").strip()
        if not text:
            raise ValueError("vector_screen requires text")
        payload["text"] = text[:60000]

    elif job_type == JOB_CODEX_APPLY:
        # Payload is fully provided via `extra` at enqueue time.
        title = (payload.get("title") or "").strip()
        description = (payload.get("description") or "").strip()
        if len(description) < 40:
            raise ValueError("codex_apply requires a job description")
        payload["title"] = title or "Target role"
        payload["description"] = description[:60000]
        payload["company"] = (payload.get("company") or "")[:200]
        payload["job_url"] = (payload.get("job_url") or "")[:500]
        payload["chat_id"] = int(payload.get("chat_id") or entity_id)
        payload["telegram_user_id"] = int(payload.get("telegram_user_id") or entity_id)
        if payload.get("improve"):
            payload["improve"] = True
            if payload.get("application_id") is not None:
                payload["application_id"] = int(payload["application_id"])
            payload["evaluation_md"] = (payload.get("evaluation_md") or "")[:200000]
            payload["previous_resume_md"] = (payload.get("previous_resume_md") or "")[:200000]
            payload["previous_output_dir"] = (payload.get("previous_output_dir") or "")[:1024]
            payload["ats_guidance"] = (payload.get("ats_guidance") or "")[:12000]
            try:
                payload["previous_ats_score"] = int(payload.get("previous_ats_score") or 0)
            except (TypeError, ValueError):
                payload["previous_ats_score"] = 0

    return payload


def find_active(db: Session, job_type: str, entity_id: int) -> WorkJob | None:
    return (
        db.query(WorkJob)
        .filter(
            WorkJob.job_type == job_type,
            WorkJob.entity_id == entity_id,
            WorkJob.status.in_(ACTIVE_STATUSES),
        )
        .order_by(WorkJob.id.desc())
        .first()
    )


def enqueue_work(
    db: Session,
    job_type: str,
    entity_id: int,
    *,
    extra: dict | None = None,
    dedupe: bool = True,
) -> WorkJob:
    if dedupe:
        existing = find_active(db, job_type, entity_id)
        if existing:
            logger.info("Work job already queued id=%s type=%s entity=%s", existing.id, job_type, entity_id)
            return existing

    payload = build_payload(db, job_type, entity_id, extra)
    row = WorkJob(
        job_type=job_type,
        entity_id=entity_id,
        status="pending",
        payload_json=json.dumps(payload, ensure_ascii=False, default=str),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("Enqueued work job id=%s type=%s entity=%s", row.id, job_type, entity_id)
    return row


def reclaim_stale(db: Session) -> int:
    cutoff = _now() - timedelta(minutes=CLAIM_STALE_MINUTES)
    rows = (
        db.query(WorkJob)
        .filter(WorkJob.status == "claimed", WorkJob.claimed_at.isnot(None))
        .all()
    )
    n = 0
    for row in rows:
        claimed_at = row.claimed_at
        if claimed_at and claimed_at.tzinfo is None:
            claimed_at = claimed_at.replace(tzinfo=timezone.utc)
        if claimed_at and claimed_at < cutoff:
            row.status = "pending"
            row.claimed_by = None
            row.claimed_at = None
            row.error_message = "Reclaimed after stale claim"
            n += 1
    if n:
        db.commit()
    return n


def claim_next(
    db: Session,
    worker_id: str,
    *,
    only_types: set[str] | None = None,
) -> WorkJob | None:
    reclaim_stale(db)
    q = db.query(WorkJob).filter(WorkJob.status == "pending")
    if only_types:
        q = q.filter(WorkJob.job_type.in_(list(only_types)))
    row = q.order_by(WorkJob.id.asc()).first()
    if not row:
        return None
    # Refresh payload with latest entity state (preserve bridge payloads)
    try:
        if row.job_type in (JOB_VECTOR_SCREEN, JOB_CODEX_APPLY):
            existing = {}
            if row.payload_json:
                try:
                    existing = json.loads(row.payload_json)
                except json.JSONDecodeError:
                    existing = {}
            if row.job_type == JOB_VECTOR_SCREEN:
                payload = build_payload(
                    db,
                    row.job_type,
                    row.entity_id,
                    {"text": existing.get("text") or ""},
                )
            else:
                payload = build_payload(db, row.job_type, row.entity_id, existing)
            row.payload_json = json.dumps(payload, ensure_ascii=False, default=str)
        else:
            payload = build_payload(db, row.job_type, row.entity_id)
            row.payload_json = json.dumps(payload, ensure_ascii=False, default=str)
    except Exception as exc:
        row.status = "failed"
        row.error_message = str(exc)[:2000]
        row.completed_at = _now()
        db.commit()
        logger.exception("Failed to build payload for work job %s", row.id)
        return None

    row.status = "claimed"
    row.claimed_by = worker_id[:128]
    row.claimed_at = _now()
    db.commit()
    db.refresh(row)
    return row


def work_job_dict(row: WorkJob) -> dict:
    payload = {}
    if row.payload_json:
        try:
            payload = json.loads(row.payload_json)
        except json.JSONDecodeError:
            payload = {}
    result = None
    if row.result_json:
        try:
            result = json.loads(row.result_json)
        except json.JSONDecodeError:
            result = None
    return {
        "id": row.id,
        "job_type": row.job_type,
        "entity_id": row.entity_id,
        "status": row.status,
        "payload": payload,
        "result": result,
        "error_message": row.error_message,
        "claimed_by": row.claimed_by,
        "claimed_at": row.claimed_at.isoformat() if row.claimed_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def wait_for_work_job(job_id: int, *, timeout_seconds: float = 90.0) -> dict[str, Any]:
    """Poll until a work job is done/failed. Returns result dict on success."""
    import asyncio

    from app.database import SessionLocal

    deadline = asyncio.get_event_loop().time() + max(5.0, timeout_seconds)
    while True:
        db = SessionLocal()
        try:
            row = db.get(WorkJob, job_id)
            if not row:
                raise RuntimeError(f"Work job {job_id} not found")
            if row.status == "done":
                if not row.result_json:
                    return {}
                try:
                    return json.loads(row.result_json)
                except json.JSONDecodeError:
                    return {}
            if row.status == "failed":
                raise RuntimeError(row.error_message or f"Work job {job_id} failed")
        finally:
            db.close()

        if asyncio.get_event_loop().time() >= deadline:
            raise TimeoutError(f"Work job {job_id} timed out after {timeout_seconds:.0f}s")
        await asyncio.sleep(0.4)
