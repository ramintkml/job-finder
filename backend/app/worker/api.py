"""Worker API — PC worker heartbeat / claim / complete (protected by WORKER_API_SECRET)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import WorkJob, get_db
from app.worker.apply import apply_work_result, fail_work_job
from app.worker.queue import (
    claim_next,
    JOB_CODEX_APPLY,
    JOB_SAVE_FILES,
    queue_heavy_enabled,
    record_heartbeat,
    work_job_dict,
    worker_status,
)

router = APIRouter(prefix="/worker", tags=["worker"])


def _configured_worker_secret() -> str:
    """Prefer settings, then fall back to backend/.env (PM2 may inject empty env vars)."""
    secret = (settings.worker_api_secret or "").strip()
    if secret:
        return secret
    try:
        from dotenv import dotenv_values

        from app.config import ROOT_DIR

        values = dotenv_values(ROOT_DIR / "backend" / ".env")
        return (values.get("WORKER_API_SECRET") or "").strip()
    except Exception:
        return ""


def _require_worker_secret(authorization: str | None = Header(default=None)) -> None:
    secret = _configured_worker_secret()
    if not secret:
        raise HTTPException(503, "WORKER_API_SECRET not configured on server")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Bearer token")
    token = authorization[7:].strip()
    if token != secret:
        raise HTTPException(403, "Invalid worker secret")


class HeartbeatBody(BaseModel):
    worker_id: str = Field(min_length=1, max_length=128)
    name: str = ""
    telethon_connected: bool | None = None
    telethon_needs_auth: bool | None = None
    rag_chroma: bool | None = None


class ClaimBody(BaseModel):
    worker_id: str = Field(min_length=1, max_length=128)
    telethon_connected: bool | None = None
    telethon_needs_auth: bool | None = None
    rag_chroma: bool | None = None


class CompleteBody(BaseModel):
    ok: bool = True
    result: dict[str, Any] | None = None
    error: str | None = None


@router.get("/status")
def get_worker_status(db: Session = Depends(get_db)):
    """Public dashboard status (no secret)."""
    return worker_status(db)


@router.post("/heartbeat")
def worker_heartbeat(
    body: HeartbeatBody,
    db: Session = Depends(get_db),
    _: None = Depends(_require_worker_secret),
):
    record_heartbeat(
        db,
        body.worker_id,
        body.name,
        telethon_connected=body.telethon_connected,
        telethon_needs_auth=body.telethon_needs_auth,
        rag_chroma=body.rag_chroma,
    )
    return {"ok": True, **worker_status(db)}


@router.post("/claim")
def worker_claim(
    body: ClaimBody,
    db: Session = Depends(get_db),
    _: None = Depends(_require_worker_secret),
):
    record_heartbeat(
        db,
        body.worker_id,
        telethon_connected=body.telethon_connected,
        telethon_needs_auth=body.telethon_needs_auth,
        rag_chroma=body.rag_chroma,
    )
    if queue_heavy_enabled():
        row = claim_next(db, body.worker_id)
    else:
        # Codex bridge + FA artifact sync still work when heavy-queue mode is off
        row = claim_next(
            db, body.worker_id, only_types={JOB_CODEX_APPLY, JOB_SAVE_FILES}
        )
    if not row:
        return {"ok": True, "job": None}
    return {"ok": True, "job": work_job_dict(row)}


@router.post("/jobs/{job_id}/complete")
async def worker_complete(
    job_id: int,
    body: CompleteBody,
    db: Session = Depends(get_db),
    _: None = Depends(_require_worker_secret),
):
    row = db.get(WorkJob, job_id)
    if not row:
        raise HTTPException(404, "Work job not found")
    if row.status not in ("claimed", "pending"):
        raise HTTPException(400, f"Job is {row.status}, cannot complete")

    if not body.ok:
        await fail_work_job(db, row, body.error or "Worker reported failure")
        return {"ok": True, "status": "failed"}

    result = body.result or {}
    out = await apply_work_result(db, row, result)
    return {"ok": bool(out.get("ok")), "apply": out, "status": row.status}
