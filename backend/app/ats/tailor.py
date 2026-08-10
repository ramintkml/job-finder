"""AI resume tailor — supports LinkedInJob rows or free-form job + base CV text."""

from __future__ import annotations

import logging
import re

from app.config import CV_MD_PATH
from app.database import LinkedInJob

logger = logging.getLogger(__name__)


def load_base_cv_text() -> str:
    if CV_MD_PATH.exists():
        return CV_MD_PATH.read_text(encoding="utf-8")
    raise FileNotFoundError(f"Base CV not found at {CV_MD_PATH}")


def job_requests_pdf(description: str, title: str = "") -> bool:
    blob = f"{title}\n{description}".lower()
    return bool(re.search(r"\bpdf\b", blob)) and not re.search(
        r"\b(docx?|word document)\b", blob
    )


async def tailor_resume_from_texts(
    *,
    base_cv: str,
    title: str,
    description: str,
    company: str = "",
    location: str = "",
    job_url: str = "",
    prior_tips: dict | None = None,
    prior_scoring: dict | None = None,
) -> dict:
    """Return structured resume JSON via pipeline v2 (ledger → write → hard_insert)."""
    from app.ats.pipeline_v2 import run_pipeline_v2

    return await run_pipeline_v2(
        base_cv=base_cv,
        title=title,
        description=description,
        company=company,
        location=location,
        job_url=job_url,
        prior_tips=prior_tips,
        prior_scoring=prior_scoring,
    )


async def tailor_resume_for_job(
    job: LinkedInJob,
    *,
    prior_tips: dict | None = None,
    prior_scoring: dict | None = None,
) -> dict:
    """Tailor using the default on-disk base CV + a LinkedInJob row."""
    return await tailor_resume_from_texts(
        base_cv=load_base_cv_text(),
        title=job.title or "",
        description=job.description or "",
        company=job.company or "",
        location=job.location or "",
        job_url=job.job_url or "",
        prior_tips=prior_tips,
        prior_scoring=prior_scoring,
    )
