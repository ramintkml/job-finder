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
        "ats_score": row.ats_score if (scores or {}).get("method_version") == "3.0" else None,
        "ats_assessment": scores if (scores or {}).get("method_version") == "3.0" else {"notice":"این نتیجه قدیمی است؛ برای ارزیابی جدید رزومه را بهبود دهید."},
        "has_resume_pdf": bool(row.resume_pdf_path and Path(row.resume_pdf_path).is_file()),
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
from pydantic import BaseModel

class DocumentRequest(BaseModel):
    kind: str
    language: str

@router.post('/{application_id}/documents')
def request_variant(application_id:int, body:DocumentRequest, db:Session=Depends(get_db), user:Principal=Depends(current_user)):
    from app.services.documents import request_document
    row=db.get(BotApplication,application_id)
    if not row or (not user.is_admin and row.telegram_user_id!=user.telegram_user_id): raise HTTPException(404,'Application not found')
    try: item=request_document(db,row,row.telegram_user_id,body.kind,body.language)
    except ValueError as exc: raise HTTPException(422,str(exc))
    return {'id':item.id,'status':item.status}

@router.get('/{application_id}/documents')
def list_documents(application_id:int, db:Session=Depends(get_db), user:Principal=Depends(current_user)):
    import json
    from app.database import DocumentArtifact
    row=db.get(BotApplication,application_id)
    if not row or (not user.is_admin and row.telegram_user_id!=user.telegram_user_id): raise HTTPException(404,'Application not found')
    items=db.query(DocumentArtifact).filter_by(application_id=row.id,owner_id=row.telegram_user_id).order_by(DocumentArtifact.id.desc()).all()
    from app.database import WorkJob
    for item in items:
        if item.status == "pending" and item.work_job_id:
            job = db.get(WorkJob, item.work_job_id)
            if job and job.status in ("failed", "cancelled"):
                item.status = "failed"
                item.error = "پردازش کامل نشد؛ دوباره تلاش کنید."
    db.commit()
    return [{'id':i.id,'kind':i.kind,'language':i.language,'status':i.status,'error':i.error,'checks':json.loads(i.checks_json or '{}')} for i in items]

@router.get('/{application_id}/documents/{artifact_id}/{extension}')
def download_document(application_id:int,artifact_id:int,extension:str,db:Session=Depends(get_db),user:Principal=Depends(current_user)):
    from app.database import DocumentArtifact
    row=db.get(BotApplication,application_id);item=db.get(DocumentArtifact,artifact_id)
    if not row or not item or item.application_id!=row.id or item.owner_id!=row.telegram_user_id or (not user.is_admin and row.telegram_user_id!=user.telegram_user_id): raise HTTPException(404,'Document not found')
    if extension not in ('docx','pdf'): raise HTTPException(404,'Document not found')
    raw=getattr(item,extension+'_path');path=Path(raw) if raw else None
    if item.status!='ready' or not path or not path.is_file(): raise HTTPException(404,'File not ready')
    return FileResponse(path,filename=f'{item.kind}-{item.language}.{extension}')

@router.get('/{application_id}/resume.pdf')
def download_primary_pdf(application_id:int, db:Session=Depends(get_db), user:Principal=Depends(current_user)):
    row=db.get(BotApplication,application_id)
    if not row or (not user.is_admin and row.telegram_user_id!=user.telegram_user_id): raise HTTPException(404,'Application not found')
    path=Path(row.resume_pdf_path) if row.resume_pdf_path else None
    if not path or not path.is_file(): raise HTTPException(404,'PDF not ready')
    return FileResponse(path,filename='resume.pdf')
