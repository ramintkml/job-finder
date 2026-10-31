"""API for Telegram/Codex bot applications (jobs + generated resumes)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import BotApplication, get_db
from app.api.auth import Principal, current_user

router = APIRouter(prefix="/applications", tags=["applications"])


def application_dict(row: BotApplication) -> dict:
    scores = None
    if row.ats_scores_json:
        try:
            import json

            scores = json.loads(row.ats_scores_json)
        except Exception:
            scores = None
    return {
        "id": row.id,
        "telegram_user_id": row.telegram_user_id,
        "work_job_id": row.work_job_id,
        "title": row.title or "",
        "company": row.company or "",
        "job_url": row.job_url or "",
        "fit_score": row.fit_score,
        "ats_score": row.ats_score,
        "ats_band": (scores or {}).get("band") if isinstance(scores, dict) else None,
        "ats_categories": (scores or {}).get("categories") if isinstance(scores, dict) else None,
        "ats_keyword_missing": (scores or {}).get("keyword_missing") if isinstance(scores, dict) else None,
        "recommendation": row.recommendation or "",
        "summary": row.summary or "",
        "ats_notes": row.ats_notes or "",
        "status": row.status or "ready",
        "has_resume_docx": bool(row.resume_docx_path and Path(row.resume_docx_path).is_file()),
        "has_resume_md": bool((row.resume_md or "").strip()),
        "has_evaluation": bool((row.evaluation_md or "").strip()),
        "output_dir": row.output_dir or "",
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("")
def list_applications(db: Session = Depends(get_db), user: Principal = Depends(current_user)):
    rows = (
        db.query(BotApplication)
        .filter(True if user.is_admin else BotApplication.telegram_user_id == user.telegram_user_id)
        .order_by(BotApplication.created_at.desc(), BotApplication.id.desc())
        .limit(200)
        .all()
    )
    return [application_dict(r) for r in rows]


@router.get("/{application_id}")
def get_application(application_id: int, db: Session = Depends(get_db), user: Principal = Depends(current_user)):
    row = db.get(BotApplication, application_id)
    if not row or (not user.is_admin and row.telegram_user_id != user.telegram_user_id):
        raise HTTPException(404, "Application not found")
    payload = application_dict(row)
    payload["description"] = (row.description or "")[:20000]
    payload["evaluation_md"] = row.evaluation_md or ""
    payload["resume_md"] = row.resume_md or ""
    return payload


@router.get("/{application_id}/resume.docx")
def download_resume_docx(application_id: int, db: Session = Depends(get_db), user: Principal = Depends(current_user)):
    row = db.get(BotApplication, application_id)
    if not row or (not user.is_admin and row.telegram_user_id != user.telegram_user_id):
        raise HTTPException(404, "Application not found")
    path = Path(row.resume_docx_path) if row.resume_docx_path else None
    if not path or not path.is_file():
        raise HTTPException(404, "DOCX resume not found")
    company = (row.company or "company").strip() or "company"
    title = (row.title or "resume").strip() or "resume"
    filename = f"{company}_{title}.docx".replace("/", "-")[:120]
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
    )


@router.delete("/{application_id}")
def delete_application(application_id: int, db: Session = Depends(get_db), user: Principal = Depends(current_user)):
    row = db.get(BotApplication, application_id)
    if not row or (not user.is_admin and row.telegram_user_id != user.telegram_user_id):
        raise HTTPException(404, "Application not found")
    db.delete(row)
    db.commit()
    return {"ok": True}
