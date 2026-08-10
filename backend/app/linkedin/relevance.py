"""Score LinkedIn jobs against proposal guide / CV vector index."""

from __future__ import annotations

from app.database import LinkedInJob
from app.rag.chunks import SKIP_THRESHOLD
from app.rag.store import collection_count, query_project

DEFAULT_LIST_CV_MATCH_THRESHOLD = SKIP_THRESHOLD  # 65
DEFAULT_EMAIL_CV_MATCH_THRESHOLD = 70


def job_text(job: LinkedInJob) -> str:
    return f"{job.title}\n{job.company}\n{job.location}\n{job.description}".strip()


def score_text_relevance(text: str) -> int | None:
    """Sync local score (lean or chroma on this host). Prefer score_text_relevance_async on VPS."""
    if collection_count() == 0:
        return None
    cleaned = text.strip()
    if not cleaned:
        return 0
    hits = query_project(cleaned, n_results=1)
    if not hits:
        return 0
    return max(0, min(100, int(round(hits[0]["similarity"] * 100))))


async def score_text_relevance_async(text: str) -> int | None:
    """Prefer PC chroma when VPS only has lean TF-IDF (same path as Freelancer matching)."""
    cleaned = (text or "").strip()
    if not cleaned:
        return 0
    from app.rag.matcher import vector_screen_project_async

    result = await vector_screen_project_async(cleaned)
    reason = (result.skip_reason or "").lower()
    if "not built" in reason or "index not" in reason:
        return None
    return max(0, min(100, int(result.confidence)))


def score_job_relevance(job: LinkedInJob) -> int | None:
    return score_text_relevance(job_text(job))


async def score_job_relevance_async(job: LinkedInJob) -> int | None:
    return await score_text_relevance_async(job_text(job))


def meets_list_relevance_threshold(
    score: int | None,
    *,
    threshold: int = DEFAULT_LIST_CV_MATCH_THRESHOLD,
) -> tuple[bool, str]:
    if score is None:
        return (
            False,
            "CV match unavailable — refresh proposal guide index in Settings → Freelancer",
        )
    if score < threshold:
        return False, f"CV match {score}% — below {threshold}%"
    return True, ""


def meets_email_relevance_threshold(
    score: int | None,
    *,
    threshold: int = DEFAULT_EMAIL_CV_MATCH_THRESHOLD,
) -> tuple[bool, str]:
    if score is None:
        return (
            False,
            "CV match unavailable — refresh proposal guide index in Settings → Freelancer",
        )
    if score < threshold:
        return False, f"CV match {score}% — below {threshold}% (email threshold)"
    return True, ""


def meets_relevance_threshold(
    score: int | None,
    *,
    threshold: int = DEFAULT_LIST_CV_MATCH_THRESHOLD,
) -> tuple[bool, str]:
    return meets_list_relevance_threshold(score, threshold=threshold)


def ensure_job_relevance_score(job: LinkedInJob, db) -> int | None:
    if job.relevance_score is not None:
        return job.relevance_score
    score = score_job_relevance(job)
    if score is not None:
        job.relevance_score = score
        db.commit()
    return score


async def ensure_job_relevance_score_async(
    job: LinkedInJob,
    db,
    *,
    force: bool = False,
) -> int | None:
    """Fill or refresh CV match score (PC chroma when VPS is lean)."""
    if job.relevance_score is not None and not force:
        # Lean TF-IDF often underscored AI jobs — refresh low scores via PC when available.
        from app.config import settings
        from app.database import SessionLocal
        from app.rag.store import backend_name
        from app.worker.queue import queue_heavy_enabled, worker_status

        refresh = False
        if (
            backend_name() == "lean"
            and settings.queue_heavy_work
            and queue_heavy_enabled()
            and job.relevance_score < 50
        ):
            check_db = SessionLocal()
            try:
                st = worker_status(check_db)
                refresh = bool(st.get("worker_online") and st.get("worker_rag_chroma"))
            finally:
                check_db.close()
        if not refresh:
            return job.relevance_score

    score = await score_job_relevance_async(job)
    if score is not None:
        job.relevance_score = score
        db.commit()
    return score
