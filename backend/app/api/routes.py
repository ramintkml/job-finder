from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.evaluator import load_guide, save_guide
from app.config import settings
from app.database import AppSettings, Project, get_db
from app.telegram.service import telegram_service

router = APIRouter()


class ProjectOut(BaseModel):
    id: int
    freelancer_project_id: str | None
    title: str
    description: str
    budget_text: str
    is_hourly: bool
    currency: str
    status: str
    skip_reason: str | None
    review_reason: str | None
    confidence: int | None
    proposal: str | None
    bid_amount: float | None
    bid_duration: int | None
    duration_type: str | None
    auto_bid: bool
    error_message: str | None
    source: str | None = None
    created_at: datetime
    submitted_at: datetime | None

    model_config = {"from_attributes": True}


class SettingsOut(BaseModel):
    ai_provider: str
    ai_model: str
    ai_screening_provider: str
    ai_screening_model: str
    ai_proposal_provider: str
    ai_proposal_model: str
    auto_bid_confidence_threshold: int
    max_bids_per_day: int
    test_mode: bool
    api_key_set: bool
    screening_api_key_set: bool
    proposal_api_key_set: bool
    bids_today: int
    telegram_connected: bool
    telegram_needs_auth: bool
    channel_configured: bool
    freelancer_channel_configured: bool
    linkedin_channel_configured: bool
    review_bot_configured: bool
    bid_step: str
    automation_enabled: bool
    freelancer_bidding_enabled: bool
    freelancer_connected: bool
    freelancer_sandbox: bool
    freelancer_client_configured: bool
    freelancer_username: str | None
    freelancer_user_id: str | None
    queue_heavy_work: bool = False
    worker_online: bool = False
    worker_pending: int = 0
    worker_claimed: int = 0
    worker_last_seen_at: str | None = None
    worker_name: str | None = None
    worker_telethon_connected: bool = False
    worker_telethon_needs_auth: bool = False


class SettingsUpdate(BaseModel):
    codex_model: str | None = None
    ai_provider: str | None = None
    ai_model: str | None = None
    ai_screening_provider: str | None = None
    ai_screening_model: str | None = None
    ai_proposal_provider: str | None = None
    ai_proposal_model: str | None = None
    auto_bid_confidence_threshold: int | None = None
    max_bids_per_day: int | None = None
    test_mode: bool | None = None
    api_key: str | None = None
    api_key_provider: str | None = None
    screening_api_key: str | None = None
    proposal_api_key: str | None = None


class GuideUpdate(BaseModel):
    content: str


class TelegramLoginRequest(BaseModel):
    code: str
    password: str | None = None


class StatsOut(BaseModel):
    total: int
    submitted: int
    skipped: int
    pending_review: int
    test_ready: int
    failed: int
    bids_today: int
    max_bids_per_day: int
    test_mode: bool
    automation_enabled: bool
    freelancer_bidding_enabled: bool


def _persist_setting(db: Session, key: str, value: str) -> None:
    from app.services.settings_service import persist_setting

    persist_setting(db, key, value)


def _api_key_for_provider(provider: str) -> str:
    return ""  # Codex uses its CLI login, not keys managed by this app.


def _set_api_key_for_provider(provider: str, value: str) -> None:
    raise HTTPException(400, "API keys are retired. Run codex login on the PC.")


def _api_key_setting_name(provider: str) -> str:
    raise HTTPException(400, "API keys are retired. Run codex login on the PC.")


def _validate_provider(provider: str) -> None:
    if provider != "codex":
        raise HTTPException(400, "Only codex is supported")


def _persist_provider_settings(body: SettingsUpdate, db: Session) -> None:
    for field in ("ai_provider", "ai_screening_provider", "ai_proposal_provider"):
        value = getattr(body, field)
        if value is not None:
            _validate_provider(value)
    if any(getattr(body, field) for field in ("ai_model", "ai_screening_model", "ai_proposal_model")):
        raise HTTPException(400, "Set codex_model for all AI roles instead")
    if body.codex_model is not None:
        import re
        if not re.fullmatch(r"[A-Za-z0-9._-]{0,128}", body.codex_model):
            raise HTTPException(400, "Invalid Codex model identifier")
        settings.codex_model = body.codex_model
        _persist_setting(db, "codex_model", body.codex_model)
    for field in ("ai_provider", "ai_screening_provider", "ai_proposal_provider"):
        setattr(settings, field, "codex")
        _persist_setting(db, field, "codex")


def _load_runtime_settings(db: Session) -> None:
    from app.services.settings_service import apply_persisted_settings

    apply_persisted_settings(db)


@router.get("/stats", response_model=StatsOut)
def get_stats(db: Session = Depends(get_db)):
    return StatsOut(
        total=db.query(Project).count(),
        submitted=db.query(Project).filter_by(status="submitted").count(),
        skipped=db.query(Project).filter_by(status="skipped").count(),
        pending_review=db.query(Project).filter_by(status="pending_review").count(),
        test_ready=db.query(Project).filter_by(status="test_ready").count(),
        failed=db.query(Project).filter_by(status="failed").count(),
        bids_today=telegram_service.get_bids_today(db),
        max_bids_per_day=settings.max_bids_per_day,
        test_mode=settings.test_mode,
        automation_enabled=telegram_service.automation_enabled,
        freelancer_bidding_enabled=settings.freelancer_bidding_enabled,
    )


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(
    status: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    q = db.query(Project).order_by(Project.created_at.desc())
    if status:
        q = q.filter(Project.status == status)
    return q.limit(limit).all()


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.post("/projects/{project_id}/approve")
async def approve_project(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if project.status != "pending_review":
        raise HTTPException(400, "Project is not pending review")
    return await _submit_project_bid(db, project)


@router.post("/projects/{project_id}/send-bid")
async def send_bid_for_skipped_project(project_id: int, db: Session = Depends(get_db)):
    """Generate (if needed) and submit a bid for a previously skipped project."""
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if project.status != "skipped":
        raise HTTPException(400, "Only skipped projects can be sent from this action")
    project.skip_reason = None
    db.commit()
    return await _submit_project_bid(db, project)


async def _submit_project_bid(db: Session, project: Project) -> dict:
    raise HTTPException(
        410,
        "Freelancer bidding has been removed from LinkedIn Job Finder.",
    )


@router.post("/projects/{project_id}/skip")
def skip_project(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    from app.services.project_service import skip_project_review

    skip_project_review(db, project, project.skip_reason or "Manually skipped")
    return {"ok": True}


@router.post("/projects/{project_id}/cancel")
def cancel_project(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if project.status not in ("queued", "test_ready", "bidding", "generating"):
        raise HTTPException(400, "This project cannot be cancelled")
    if project.status == "bidding":
        telegram_service.abort_bid_if_active(project_id)
    project.status = "skipped"
    project.skip_reason = "Cancelled by user"
    db.commit()
    return {"ok": True}


@router.get("/settings", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db)):
    from app.worker.queue import worker_status

    _load_runtime_settings(db)
    ws = worker_status(db)
    return SettingsOut(
        ai_provider=settings.ai_provider,
        ai_model=settings.proposal_model(),
        ai_screening_provider=settings.screening_provider,
        ai_screening_model=settings.ai_screening_model,
        ai_proposal_provider=settings.proposal_provider,
        ai_proposal_model=settings.ai_proposal_model,
        auto_bid_confidence_threshold=settings.auto_bid_confidence_threshold,
        max_bids_per_day=settings.max_bids_per_day,
        test_mode=settings.test_mode,
        api_key_set=bool(_api_key_for_provider(settings.ai_provider)),
        screening_api_key_set=bool(_api_key_for_provider(settings.screening_provider)),
        proposal_api_key_set=bool(_api_key_for_provider(settings.proposal_provider)),
        bids_today=telegram_service.get_bids_today(db),
        telegram_connected=telegram_service.connected,
        telegram_needs_auth=telegram_service.needs_auth,
        channel_configured=(
            telegram_service.uses_review_bot()
            or bool(settings.telegram_channel_id.strip())
        ),
        freelancer_channel_configured=False,
        linkedin_channel_configured=(
            telegram_service.uses_review_bot()
            or bool(settings.telegram_linkedin_channel_id.strip())
        ),
        review_bot_configured=telegram_service.uses_review_bot(),
        bid_step=telegram_service.step.value,
        automation_enabled=telegram_service.automation_enabled,
        freelancer_connected=False,
        freelancer_sandbox=False,
        freelancer_client_configured=False,
        freelancer_bidding_enabled=False,
        freelancer_username=None,
        freelancer_user_id=None,
        queue_heavy_work=ws["queue_heavy_work"],
        worker_online=ws["worker_online"],
        worker_pending=ws["pending"],
        worker_claimed=ws["claimed"],
        worker_last_seen_at=ws["last_seen_at"],
        worker_name=ws["worker_name"],
        worker_telethon_connected=bool(ws.get("telethon_connected")),
        worker_telethon_needs_auth=bool(ws.get("telethon_needs_auth")),
    )


@router.put("/settings")
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db)):
    _persist_provider_settings(body, db)
    if body.auto_bid_confidence_threshold is not None:
        settings.auto_bid_confidence_threshold = body.auto_bid_confidence_threshold
        _persist_setting(db, "auto_bid_confidence_threshold", str(body.auto_bid_confidence_threshold))
    if body.max_bids_per_day is not None:
        settings.max_bids_per_day = body.max_bids_per_day
        _persist_setting(db, "max_bids_per_day", str(body.max_bids_per_day))
    if body.test_mode is not None:
        settings.test_mode = body.test_mode
        _persist_setting(db, "test_mode", "true" if body.test_mode else "false")

    def save_key(provider: str, value: str) -> None:
        key_name = _api_key_setting_name(provider)
        _set_api_key_for_provider(provider, value.strip())
        _persist_setting(db, key_name, value.strip())

    if body.screening_api_key is not None and body.screening_api_key.strip():
        save_key(settings.screening_provider, body.screening_api_key)
    if body.proposal_api_key is not None and body.proposal_api_key.strip():
        save_key(settings.proposal_provider, body.proposal_api_key)
    if body.api_key is not None and body.api_key.strip():
        provider = body.api_key_provider or settings.ai_provider
        _validate_provider(provider)
        save_key(provider, body.api_key)

    return {
        "ok": True,
        "ai_screening_provider": settings.screening_provider,
        "ai_proposal_provider": settings.proposal_provider,
        "screening_api_key_set": bool(_api_key_for_provider(settings.screening_provider)),
        "proposal_api_key_set": bool(_api_key_for_provider(settings.proposal_provider)),
    }


@router.post("/ai/test")
async def test_ai_connection():
    """Test screening and proposal AI providers."""
    from app.ai.evaluator import ai_screen_project, generate_proposal, screen_project

    sample = _sample_project_text()
    out: dict = {"ok": True, "test_mode": settings.test_mode}

    try:
        screening = await screen_project(sample)
        from app.rag.matcher import index_status

        rag = index_status()
        out["screening"] = {
            "ok": True,
            "action": screening.action,
            "confidence": screening.confidence,
            "provider": "vector",
            "model": "local RAG",
            "review_reason": screening.review_reason,
            "skip_reason": screening.skip_reason,
            "index_ready": rag["ready"],
        }
    except Exception as exc:
        out["screening"] = {
            "ok": False,
            "provider": "vector",
            "model": "local RAG",
            "error": str(exc),
        }
        out["ok"] = False

    try:
        ai_screening = await ai_screen_project(sample)
        out["ai_screening"] = {
            "ok": True,
            "action": ai_screening.action,
            "confidence": ai_screening.confidence,
            "provider": settings.screening_provider,
            "model": settings.screening_model(),
            "review_reason": ai_screening.review_reason,
            "skip_reason": ai_screening.skip_reason,
        }
    except Exception as exc:
        out["ai_screening"] = {
            "ok": False,
            "provider": settings.screening_provider,
            "model": settings.screening_model(),
            "error": str(exc),
        }
        out["ok"] = False

    try:
        proposal = await generate_proposal(sample)
        out["proposal"] = {
            "ok": True,
            "amount": proposal.amount,
            "duration": proposal.duration,
            "currency": proposal.currency,
            "provider": settings.proposal_provider,
            "model": settings.proposal_model(),
        }
    except Exception as exc:
        out["proposal"] = {
            "ok": False,
            "provider": settings.proposal_provider,
            "model": settings.proposal_model(),
            "error": str(exc),
        }
        out["ok"] = False

    if not out["ok"]:
        return out

    return out


@router.post("/automation/start")
async def start_automation(db: Session = Depends(get_db)):
    await telegram_service.resume_automation()
    _persist_setting(db, "automation_enabled", "true")
    settings.automation_enabled = True
    return {
        "ok": True,
        "automation_enabled": telegram_service.automation_enabled,
        "telegram_connected": telegram_service.connected,
    }


@router.post("/automation/stop")
async def stop_automation(db: Session = Depends(get_db)):
    await telegram_service.pause_automation()
    _persist_setting(db, "automation_enabled", "false")
    settings.automation_enabled = False
    return {
        "ok": True,
        "automation_enabled": telegram_service.automation_enabled,
        "telegram_connected": telegram_service.connected,
    }


@router.post("/freelancer/bidding/start")
def start_freelancer_bidding(db: Session = Depends(get_db)):
    raise HTTPException(410, "Freelancer bidding has been removed from LinkedIn Job Finder.")


@router.post("/freelancer/bidding/stop")
def stop_freelancer_bidding(db: Session = Depends(get_db)):
    settings.freelancer_bidding_enabled = False
    _persist_setting(db, "freelancer_bidding_enabled", "false")
    return {"ok": True, "freelancer_bidding_enabled": False}


def _sample_project_text() -> str:
    return """Project #99999999 — Python Automation Tool

I need a developer to build a Python automation script that processes Excel files and extracts structured data.

Budget: $300 - $500 USD (Fixed price)
Skills: Python, Automation, Data Processing

Requirements:
- Read Excel/CSV files from a folder
- Parse bank statement formats and output clean CSV
- Windows-compatible
- Delivery within 10 days

Please describe your relevant experience."""


@router.post("/test/run")
async def run_system_test(db: Session = Depends(get_db)):
    """Full pipeline test: AI screening + proposal, saved as a sample project."""
    from app.ai.evaluator import generate_proposal, screen_bot_project
    from app.services.project_service import (
        apply_proposal,
        apply_screening,
        create_project_from_message,
    )

    sample = _sample_project_text()

    old = db.query(Project).filter_by(freelancer_project_id="99999999").all()
    for p in old:
        db.delete(p)
    db.commit()

    steps: list[dict] = []

    steps.append({
        "step": "config",
        "ok": True,
        "detail": (
            f"Bot matching: vector ≥65% then {settings.screening_provider}/"
            f"{settings.screening_model()} AI review (auto-bid ≥{settings.auto_bid_confidence_threshold}%), "
            f"Proposal: {settings.proposal_provider}/{settings.proposal_model()}, "
            f"test_mode: {settings.test_mode}"
        ),
    })

    steps.append({
        "step": "telegram",
        "ok": telegram_service.connected,
        "detail": "Connected to @KayaProjectsBot" if telegram_service.connected else "Not connected (OK for AI-only test)",
    })

    try:
        screening = await screen_bot_project(sample)
        steps.append({
            "step": "screening",
            "ok": True,
            "detail": f"action={screening.action}, confidence={screening.confidence}%",
        })
    except Exception as exc:
        steps.append({"step": "screening", "ok": False, "detail": str(exc)})
        return {"ok": False, "steps": steps, "project_id": None}

    project = create_project_from_message(
        db,
        text=sample,
        message_id=0,
        freelancer_project_id="99999999",
    )
    project.title = "[TEST] " + project.title
    db.commit()

    apply_screening(db, project, screening, settings.auto_bid_confidence_threshold)

    if project.status == "generating" and screening.action == "bid":
        try:
            proposal = await generate_proposal(sample)
            apply_proposal(db, project, proposal)
            steps.append({
                "step": "proposal",
                "ok": True,
                "detail": f"{proposal.currency} {proposal.amount}, {proposal.duration} {proposal.duration_type}",
            })
        except Exception as exc:
            project.status = "failed"
            project.error_message = str(exc)
            db.commit()
            steps.append({"step": "proposal", "ok": False, "detail": str(exc)})
            return {"ok": False, "steps": steps, "project_id": project.id}
    elif project.status == "skipped":
        steps.append({
            "step": "proposal",
            "ok": True,
            "detail": "Skipped — no proposal generated (expected for bad projects)",
        })

    steps.append({
        "step": "bid",
        "ok": True,
        "detail": (
            "Telegram bot: auto-bid via @KayaProjectsBot when above threshold; "
            "API projects: channel send reply"
        ),
    })

    db.refresh(project)
    return {
        "ok": all(s["ok"] for s in steps if s["step"] != "telegram"),
        "steps": steps,
        "project_id": project.id,
        "project_status": project.status,
        "test_mode": settings.test_mode,
    }


@router.get("/guide")
def get_guide():
    content = load_guide()
    return {
        "content": content,
        "chars": len(content),
        "empty": not bool(content.strip()),
        "path": "data/proposal_guide.md",
    }


@router.put("/guide")
def update_guide(body: GuideUpdate):
    save_guide(body.content or "")
    return {"ok": True, "chars": len(body.content or "")}


@router.post("/guide/upload")
async def upload_guide(file: UploadFile = File(...)):
    """Replace proposal_guide.md from an uploaded .md / .txt file."""
    name = (file.filename or "").lower()
    if name and not (name.endswith(".md") or name.endswith(".txt") or name.endswith(".markdown")):
        raise HTTPException(400, "Upload a .md or .txt file")
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "File is empty")
    if len(raw) > 1_000_000:
        raise HTTPException(400, "File too large (max 1 MB)")
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(400, "File must be UTF-8 text") from exc
    save_guide(content)
    return {
        "ok": True,
        "chars": len(content),
        "filename": file.filename,
        "message": "Proposal guide uploaded. Refresh the guide index in Freelancer settings if you use RAG.",
    }


def _telegram_credentials_ok() -> bool:
    return bool(settings.telegram_api_id) and bool(str(settings.telegram_api_hash or "").strip())


def _telegram_missing_creds_hint() -> str | None:
    if not _telegram_credentials_ok():
        return (
            "TELEGRAM_API_ID and TELEGRAM_API_HASH are missing in backend/.env on the VPS. "
            "Get them from https://my.telegram.org and copy data/telegram.session to the VPS "
            "(or log in once via Settings after setting the keys)."
        )
    return None


@router.post("/telegram/login/request")
async def telegram_request_code():
    hint = _telegram_missing_creds_hint()
    if hint:
        raise HTTPException(400, hint)
    try:
        await telegram_service.request_login_code()
        return {"ok": True, "message": "Code sent to your Telegram app"}
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@router.post("/telegram/login/confirm")
async def telegram_confirm_login(body: TelegramLoginRequest):
    hint = _telegram_missing_creds_hint()
    if hint:
        raise HTTPException(400, hint)
    try:
        await telegram_service.confirm_login(body.code, body.password)
        return {"ok": True, "connected": telegram_service.connected}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@router.post("/telegram/restart")
async def telegram_restart():
    hint = _telegram_missing_creds_hint()
    if hint:
        raise HTTPException(400, hint)
    try:
        if telegram_service.client:
            await telegram_service.stop()
        await telegram_service.start()
        return {"ok": True, "connected": telegram_service.connected, "needs_auth": telegram_service.needs_auth}
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@router.post("/telegram/channel/test")
async def telegram_test_channel():
    try:
        result = await telegram_service.test_channel_notifications()
        if not result.get("ok"):
            raise HTTPException(400, result.get("error", "Channel test failed"))
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc
