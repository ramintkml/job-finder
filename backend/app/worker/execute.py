"""Execute heavy work jobs on the PC worker (AI email + ATS). Telegram stays on VPS."""

from __future__ import annotations

import base64
import json
import logging
import re
from types import SimpleNamespace
from typing import Any

from app.config import ATS_DIR
from app.worker.queue import (
    JOB_ATS_REGENERATE,
    JOB_CODEX_APPLY,
    JOB_LINKEDIN_EMAIL,
    JOB_LINKEDIN_RESUME,
    JOB_PROJECT_SEND,
    JOB_SAVE_FILES,
    JOB_VECTOR_SCREEN,
)

logger = logging.getLogger(__name__)


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "Candidate").strip())
    return cleaned.strip("_") or "Candidate"


async def execute_job(job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if job_type == JOB_LINKEDIN_EMAIL:
        return await _exec_linkedin_email(payload)
    if job_type in (JOB_LINKEDIN_RESUME, JOB_ATS_REGENERATE):
        return await _exec_ats(payload, force=job_type == JOB_ATS_REGENERATE or payload.get("force", True))
    if job_type == JOB_PROJECT_SEND:
        return await _exec_project_send(payload)
    if job_type == JOB_VECTOR_SCREEN:
        return await _exec_vector_screen(payload)
    if job_type == JOB_CODEX_APPLY:
        from app.worker.codex_apply import run_codex_apply

        return await run_codex_apply(payload)
    if job_type == JOB_SAVE_FILES:
        return await _exec_save_files(payload)
    raise ValueError(f"Unknown job type: {job_type}")


async def _exec_save_files(payload: dict) -> dict:
    """Write base64 artifacts into a local applications folder (PC worker)."""
    from pathlib import Path

    out_raw = (payload.get("output_dir") or "").strip()
    if not out_raw:
        return {"ok": False, "error": "output_dir missing"}
    out_dir = Path(out_raw)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return {"ok": False, "error": f"Cannot create output_dir: {exc}"}

    files = payload.get("files") or {}
    if not isinstance(files, dict) or not files:
        return {"ok": False, "error": "No files to save"}

    written: list[str] = []
    for name, b64 in files.items():
        safe = Path(str(name)).name
        if not safe or ".." in safe:
            continue
        try:
            raw = base64.b64decode(b64)
        except Exception:
            continue
        target = out_dir / safe
        target.write_bytes(raw)
        written.append(safe)
    if not written:
        return {"ok": False, "error": "Failed to decode/write any files"}
    return {"ok": True, "written": written, "output_dir": str(out_dir)}


async def _exec_vector_screen(payload: dict) -> dict:
    from app.rag.matcher import _screening_to_dict, vector_screen_project

    text = (payload.get("text") or "").strip()
    if not text:
        raise ValueError("vector_screen payload missing text")
    result = vector_screen_project(text)
    out = _screening_to_dict(result)
    out["backend"] = "chroma" if out.get("backend") == "chroma" else out.get("backend")
    return out


async def _exec_linkedin_email(payload: dict) -> dict:
    from dataclasses import fields

    from app.linkedin.email_compose import compose_application_email
    from app.linkedin.settings import LinkedInSettings

    job = payload.get("linkedin_job") or {}
    cfg_data = payload.get("linkedin_settings") or {}
    allowed = {f.name for f in fields(LinkedInSettings)}
    cfg = LinkedInSettings(**{k: v for k, v in cfg_data.items() if k in allowed})
    job_data = {
        "title": job.get("title") or "",
        "company": job.get("company") or "",
        "location": job.get("location") or "",
        "job_url": job.get("job_url") or "",
        "description": job.get("description") or "",
    }
    subject, body, recipient = compose_application_email(job_data, cfg)
    return {
        "email_subject": subject,
        "email_body": body,
        "recipient_email": recipient or "",
    }


def _job_namespace(job: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=job.get("id"),
        title=job.get("title") or "",
        company=job.get("company") or "",
        location=job.get("location") or "",
        job_url=job.get("job_url") or "",
        description=job.get("description") or "",
    )


async def _exec_ats(payload: dict, *, force: bool) -> dict:
    from app.ats.docx_export import export_resume_docx
    from app.ats.score import score_resume
    from app.ats.tailor import job_requests_pdf, tailor_resume_for_job
    from app.ats.tips import build_improvement_guide

    job_dict = payload.get("linkedin_job") or {}
    job = _job_namespace(job_dict)
    job_db_id = int(job_dict.get("id") or payload.get("entity_id") or 0)
    ats = payload.get("ats_resume") or {}

    prior_tips = None
    prior_scoring = None
    if force and ats.get("improvement_tips_json"):
        try:
            prior_tips = json.loads(ats["improvement_tips_json"])
        except (json.JSONDecodeError, TypeError):
            prior_tips = None
    if force and ats.get("scores_json"):
        try:
            prior_scoring = json.loads(ats["scores_json"])
            prior_scoring["total_score"] = ats.get("total_score")
            prior_scoring["keyword_missing"] = json.loads(ats.get("keyword_missing") or "[]")
            prior_scoring["keyword_matched"] = json.loads(ats.get("keyword_matched") or "[]")
        except (json.JSONDecodeError, TypeError):
            prior_scoring = None

    resume = await tailor_resume_for_job(
        job,
        prior_tips=prior_tips,
        prior_scoring=prior_scoring,
    )
    want_pdf = job_requests_pdf(job.description or "", job.title or "")
    scoring = score_resume(resume, job.description or "", include_pdf=want_pdf)
    tips = build_improvement_guide(scoring)

    first = (resume.get("full_name") or "Candidate").split()[0]
    last = "_".join((resume.get("full_name") or "Candidate").split()[1:]) or "Resume"
    base_name = f"{_safe_filename(first)}_{_safe_filename(last)}_Resume"
    out_dir = ATS_DIR / f"worker_{job_db_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    docx_path = out_dir / f"{base_name}.docx"
    export_resume_docx(resume, docx_path)

    pdf_b64 = None
    if want_pdf:
        try:
            from app.ats.pdf_export import export_resume_pdf

            pdf_file = out_dir / f"{base_name}.pdf"
            export_resume_pdf(resume, pdf_file)
            pdf_b64 = base64.b64encode(pdf_file.read_bytes()).decode("ascii")
        except Exception:
            logger.exception("PDF export failed on worker — continuing with DOCX only")

    return {
        "file_basename": base_name,
        "docx_b64": base64.b64encode(docx_path.read_bytes()).decode("ascii"),
        "pdf_b64": pdf_b64,
        "resume_json": json.dumps(resume, ensure_ascii=False),
        "scores_json": json.dumps(
            {
                "categories": scoring["categories"],
                "max_scores": scoring["max_scores"],
                "band": scoring["band"],
            },
            ensure_ascii=False,
        ),
        "total_score": int(scoring["total_score"]),
        "keyword_matched": json.dumps(scoring["keyword_matched"], ensure_ascii=False),
        "keyword_missing": json.dumps(scoring["keyword_missing"], ensure_ascii=False),
        "diff_summary": str(resume.get("diff_summary") or "").strip() or None,
        "improvement_tips_json": json.dumps(tips, ensure_ascii=False),
        "repost": payload.get("repost", True),
    }


async def _exec_project_send(payload: dict) -> dict:
    """Deprecated on PC worker — bids run on VPS with Telethon there."""
    raise RuntimeError(
        "project_send_bid is handled on the VPS (Telegram stays on the server). "
        "Re-tap Send bid in Telegram."
    )
