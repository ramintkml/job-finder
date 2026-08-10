"""Orchestrate ATS resume generation, scoring, export, and Telegram notify."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.ats.docx_export import export_resume_docx
from app.ats.score import score_resume
from app.ats.tailor import job_requests_pdf, tailor_resume_for_job
from app.ats.tips import build_improvement_guide
from app.config import ATS_DIR
from app.database import AtsResume, LinkedInJob, SessionLocal

logger = logging.getLogger(__name__)

_semaphore = asyncio.Semaphore(2)
_in_flight: set[int] = set()


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "Candidate").strip())
    return cleaned.strip("_") or "Candidate"


def _job_dir(job_db_id: int) -> Path:
    path = ATS_DIR / str(job_db_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_or_create_ats_row(db: Session, job_db_id: int) -> AtsResume:
    row = db.query(AtsResume).filter(AtsResume.linkedin_job_db_id == job_db_id).first()
    if row:
        return row
    row = AtsResume(linkedin_job_db_id=job_db_id, status="pending")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def enqueue_for_job(job_db_id: int, *, force: bool = False, repost: bool = True) -> None:
    """Schedule background generation (fire-and-forget), or queue for PC worker."""
    from app.worker.queue import JOB_LINKEDIN_RESUME, enqueue_work, queue_heavy_enabled

    if queue_heavy_enabled():
        db = SessionLocal()
        try:
            row = get_or_create_ats_row(db, job_db_id)
            row.status = "generating"
            row.error_message = None
            db.commit()
            enqueue_work(
                db,
                JOB_LINKEDIN_RESUME,
                job_db_id,
                extra={"force": force, "repost": repost},
            )
        finally:
            db.close()
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("No running loop — cannot enqueue ATS for job %s", job_db_id)
        return
    loop.create_task(generate_for_job(job_db_id, force=force, repost=repost))


async def generate_for_job(
    job_db_id: int,
    *,
    force: bool = False,
    repost: bool = True,
    force_pdf: bool | None = None,
) -> dict:
    if job_db_id in _in_flight and not force:
        return {"ok": False, "error": "Generation already in progress"}
    _in_flight.add(job_db_id)
    async with _semaphore:
        try:
            return await _generate_locked(
                job_db_id,
                force=force,
                repost=repost,
                force_pdf=force_pdf,
            )
        finally:
            _in_flight.discard(job_db_id)


async def _generate_locked(
    job_db_id: int,
    *,
    force: bool,
    repost: bool,
    force_pdf: bool | None,
) -> dict:
    db = SessionLocal()
    try:
        job = db.get(LinkedInJob, job_db_id)
        if not job:
            return {"ok": False, "error": "Job not found"}
        row = get_or_create_ats_row(db, job_db_id)
        if row.status == "ready" and not force and row.docx_path:
            return {"ok": True, "skipped": True, "id": row.id, "status": row.status}

        row.status = "generating"
        row.error_message = None
        db.commit()

        prior_tips = None
        prior_scoring = None
        if force and row.improvement_tips_json:
            try:
                prior_tips = json.loads(row.improvement_tips_json)
            except json.JSONDecodeError:
                prior_tips = None
        if force and row.scores_json:
            try:
                prior_scoring = json.loads(row.scores_json)
                prior_scoring["total_score"] = row.total_score
                prior_scoring["keyword_missing"] = json.loads(row.keyword_missing or "[]")
                prior_scoring["keyword_matched"] = json.loads(row.keyword_matched or "[]")
            except json.JSONDecodeError:
                prior_scoring = None

        resume = await tailor_resume_for_job(
            job,
            prior_tips=prior_tips,
            prior_scoring=prior_scoring,
        )
        want_pdf = force_pdf if force_pdf is not None else job_requests_pdf(
            job.description or "",
            job.title or "",
        )
        scoring = score_resume(resume, job.description or "", include_pdf=want_pdf)
        tips = build_improvement_guide(scoring)

        first = (resume.get("full_name") or "Candidate").split()[0]
        last = "_".join((resume.get("full_name") or "Candidate").split()[1:]) or "Resume"
        base_name = f"{_safe_filename(first)}_{_safe_filename(last)}_Resume"
        out_dir = _job_dir(job_db_id)
        docx_path = out_dir / f"{base_name}.docx"
        export_resume_docx(resume, docx_path)
        pdf_path = None
        if want_pdf:
            from app.ats.pdf_export import export_resume_pdf

            pdf_file = out_dir / f"{base_name}.pdf"
            export_resume_pdf(resume, pdf_file)
            pdf_path = str(pdf_file)

        row.resume_json = json.dumps(resume, ensure_ascii=False)
        row.scores_json = json.dumps(
            {
                "categories": scoring["categories"],
                "max_scores": scoring["max_scores"],
                "band": scoring["band"],
            },
            ensure_ascii=False,
        )
        row.total_score = int(scoring["total_score"])
        row.keyword_matched = json.dumps(scoring["keyword_matched"], ensure_ascii=False)
        row.keyword_missing = json.dumps(scoring["keyword_missing"], ensure_ascii=False)
        row.diff_summary = str(resume.get("diff_summary") or "").strip() or None
        row.improvement_tips_json = json.dumps(tips, ensure_ascii=False)
        row.docx_path = str(docx_path)
        row.pdf_path = pdf_path
        row.status = "ready"
        row.error_message = None
        db.commit()
        db.refresh(row)

        if repost:
            try:
                from app.telegram.service import telegram_service

                await telegram_service.notify_linkedin_ats_resume(row.id)
            except Exception:
                logger.exception("ATS channel notify failed for resume %s", row.id)

        return {
            "ok": True,
            "id": row.id,
            "status": row.status,
            "total_score": row.total_score,
            "band": scoring["band"],
        }
    except Exception as exc:
        logger.exception("ATS generation failed for job %s", job_db_id)
        row = db.query(AtsResume).filter(AtsResume.linkedin_job_db_id == job_db_id).first()
        if row:
            row.status = "failed"
            row.error_message = str(exc)[:2000]
            db.commit()
        return {"ok": False, "error": str(exc)}
    finally:
        db.close()


def ats_resume_dict(row: AtsResume, job: LinkedInJob | None = None) -> dict:
    scores = {}
    categories = {}
    band = None
    if row.scores_json:
        try:
            scores = json.loads(row.scores_json)
            categories = scores.get("categories") or {}
            band = scores.get("band")
        except json.JSONDecodeError:
            pass
    matched = []
    missing = []
    try:
        matched = json.loads(row.keyword_matched or "[]")
    except json.JSONDecodeError:
        pass
    try:
        missing = json.loads(row.keyword_missing or "[]")
    except json.JSONDecodeError:
        pass
    tips = None
    if row.improvement_tips_json:
        try:
            tips = json.loads(row.improvement_tips_json)
        except json.JSONDecodeError:
            tips = None
    return {
        "id": row.id,
        "linkedin_job_db_id": row.linkedin_job_db_id,
        "status": row.status,
        "total_score": row.total_score,
        "band": band,
        "categories": categories,
        "max_scores": scores.get("max_scores") if scores else None,
        "keyword_matched": matched,
        "keyword_missing": missing,
        "diff_summary": row.diff_summary,
        "improvement_tips": tips,
        "docx_path": row.docx_path,
        "pdf_path": row.pdf_path,
        "has_docx": bool(row.docx_path and Path(row.docx_path).exists()),
        "has_pdf": bool(row.pdf_path and Path(row.pdf_path).exists()),
        "channel_message_id": row.channel_message_id,
        "error_message": row.error_message,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "job_title": job.title if job else None,
        "company": job.company if job else None,
        "job_url": job.job_url if job else None,
        "relevance_score": job.relevance_score if job else None,
        "job_status": job.status if job else None,
    }
