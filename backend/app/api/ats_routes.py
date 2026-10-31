"""ATS resume dashboard API."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.ats.service import ats_resume_dict, enqueue_for_job, generate_for_job, get_or_create_ats_row
from app.database import AtsResume, LinkedInJob, get_db

router = APIRouter(prefix="/ats", tags=["ats"])


@router.get("/resumes")
def list_ats_resumes(
    status: str | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(AtsResume).order_by(AtsResume.updated_at.desc(), AtsResume.id.desc())
    if status == "needs_improvement":
        q = q.filter(AtsResume.status == "ready", AtsResume.total_score.isnot(None), AtsResume.total_score < 80)
    elif status:
        q = q.filter(AtsResume.status == status)
    rows = q.limit(200).all()
    job_ids = [r.linkedin_job_db_id for r in rows]
    jobs = {
        j.id: j
        for j in db.query(LinkedInJob).filter(LinkedInJob.id.in_(job_ids)).all()
    } if job_ids else {}
    return [ats_resume_dict(r, jobs.get(r.linkedin_job_db_id)) for r in rows]


@router.get("/resumes/{resume_id}")
def get_ats_resume(resume_id: int, db: Session = Depends(get_db)):
    row = db.get(AtsResume, resume_id)
    if not row:
        raise HTTPException(404, "ATS resume not found")
    job = db.get(LinkedInJob, row.linkedin_job_db_id)
    payload = ats_resume_dict(row, job)
    if row.resume_json:
        try:
            payload["resume"] = json.loads(row.resume_json)
        except json.JSONDecodeError:
            payload["resume"] = None
    return payload


@router.post("/resumes/{resume_id}/regenerate")
async def regenerate_ats_resume(
    resume_id: int,
    repost: bool = Query(False),
    pdf: bool = Query(False),
    db: Session = Depends(get_db),
):
    from app.worker.queue import JOB_ATS_REGENERATE, enqueue_work, queue_heavy_enabled

    row = db.get(AtsResume, resume_id)
    if not row:
        raise HTTPException(404, "ATS resume not found")

    if queue_heavy_enabled():
        row.status = "generating"
        row.error_message = None
        db.commit()
        work = enqueue_work(
            db,
            JOB_ATS_REGENERATE,
            resume_id,
            extra={"force": True, "repost": repost, "force_pdf": True if pdf else None},
        )
        job = db.get(LinkedInJob, row.linkedin_job_db_id)
        return {
            "ok": True,
            "queued": True,
            "work_job_id": work.id,
            "id": row.id,
            "status": row.status,
            "resume": ats_resume_dict(row, job),
        }

    result = await generate_for_job(
        row.linkedin_job_db_id,
        force=True,
        repost=repost,
        force_pdf=True if pdf else None,
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "Regenerate failed")
    db.refresh(row)
    job = db.get(LinkedInJob, row.linkedin_job_db_id)
    return {"ok": True, **result, "resume": ats_resume_dict(row, job)}


@router.post("/resumes/{resume_id}/repost")
async def repost_ats_resume(resume_id: int, db: Session = Depends(get_db)):
    row = db.get(AtsResume, resume_id)
    if not row:
        raise HTTPException(404, "ATS resume not found")
    if row.status != "ready":
        raise HTTPException(400, "Resume is not ready to repost")
    from app.telegram.service import telegram_service

    ok = await telegram_service.notify_linkedin_ats_resume(row.id)
    if not ok:
        raise HTTPException(400, "Failed to post to LinkedIn Telegram channel")
    db.refresh(row)
    return {"ok": True, "channel_message_id": row.channel_message_id}


@router.post("/jobs/{job_id}/generate")
async def generate_ats_for_job(
    job_id: int,
    repost: bool = Query(True),
    pdf: bool = Query(False),
    wait: bool = Query(True),
    db: Session = Depends(get_db),
):
    """Create/regenerate an ATS resume for a LinkedIn job.

    wait=false enqueues generation and returns immediately (UI Create resume).
    """
    from app.worker.queue import JOB_LINKEDIN_RESUME, enqueue_work, queue_heavy_enabled

    job = db.get(LinkedInJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    row = get_or_create_ats_row(db, job_id)

    if queue_heavy_enabled() or not wait:
        row.status = "generating"
        row.error_message = None
        db.commit()
        if queue_heavy_enabled():
            work = enqueue_work(
                db,
                JOB_LINKEDIN_RESUME,
                job_id,
                extra={"force": True, "repost": repost, "force_pdf": True if pdf else None},
            )
            return {
                "ok": True,
                "queued": True,
                "work_job_id": work.id,
                "id": row.id,
                "status": row.status,
                "linkedin_job_db_id": job_id,
            }
        enqueue_for_job(job_id, force=True, repost=repost)
        return {
            "ok": True,
            "queued": True,
            "id": row.id,
            "status": row.status,
            "linkedin_job_db_id": job_id,
        }
    result = await generate_for_job(
        job_id,
        force=True,
        repost=repost,
        force_pdf=True if pdf else None,
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "Generate failed")
    db.refresh(row)
    return {**result, "linkedin_job_db_id": job_id, "resume": ats_resume_dict(row, job)}


@router.get("/resumes/{resume_id}/download")
def download_ats_resume(
    resume_id: int,
    format: str = Query("docx", pattern="^(docx|pdf)$"),
    db: Session = Depends(get_db),
):
    row = db.get(AtsResume, resume_id)
    if not row:
        raise HTTPException(404, "ATS resume not found")
    path = row.docx_path if format == "docx" else row.pdf_path
    if not path or not Path(path).exists():
        raise HTTPException(404, f"{format.upper()} file not available")
    media = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if format == "docx"
        else "application/pdf"
    )
    return FileResponse(path, media_type=media, filename=Path(path).name)
