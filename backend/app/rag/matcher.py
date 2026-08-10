"""Vector-based project screening (replaces LLM screening)."""

from __future__ import annotations

import hashlib
import logging
import re

from app.ai.evaluator import ScreeningResult
from app.config import settings
from app.rag.chunks import SKIP_THRESHOLD
from app.rag.store import backend_name, chroma_available, collection_count, query_project, read_index_meta

logger = logging.getLogger(__name__)

_NON_ENGLISH_MARKERS = re.compile(
    r"[\u0600-\u06FF\u0750-\u077F\u4e00-\u9fff\u0400-\u04FF]{8,}"
)


def _detect_hourly(text: str) -> bool:
    lower = text.lower()
    return "hourly" in lower or "per hour" in lower or "/hr" in lower


def _detect_currency(text: str) -> str:
    lower = text.lower()
    if "eur" in lower or "€" in text:
        return "EUR"
    if "gbp" in lower or "£" in text:
        return "GBP"
    return "USD"


def _quick_reject(text: str) -> ScreeningResult | None:
    if _NON_ENGLISH_MARKERS.search(text):
        return ScreeningResult(
            action="skip",
            confidence=0,
            skip_reason="Non-English project",
            review_reason=None,
            is_hourly=_detect_hourly(text),
            currency=_detect_currency(text),
        )
    return None


def _result_from_dict(data: dict, text: str) -> ScreeningResult:
    return ScreeningResult(
        action=data.get("action") or "skip",
        confidence=int(data.get("confidence") or 0),
        skip_reason=data.get("skip_reason"),
        review_reason=data.get("review_reason"),
        is_hourly=bool(data.get("is_hourly", _detect_hourly(text))),
        currency=str(data.get("currency") or _detect_currency(text)),
    )


def _screening_to_dict(result: ScreeningResult) -> dict:
    return {
        "action": result.action,
        "confidence": result.confidence,
        "skip_reason": result.skip_reason,
        "review_reason": result.review_reason,
        "is_hourly": result.is_hourly,
        "currency": result.currency,
        "backend": backend_name(),
    }


def vector_screen_project(project_text: str) -> ScreeningResult:
    """Match project against local index (chroma or lean). No LLM."""
    text = project_text.strip()
    rejected = _quick_reject(text)
    if rejected:
        return rejected

    if collection_count() == 0:
        return ScreeningResult(
            action="skip",
            confidence=0,
            skip_reason="Vector index not built — click Refresh guide index in Settings → Freelancer",
            review_reason=None,
            is_hourly=_detect_hourly(text),
            currency=_detect_currency(text),
        )

    hits = query_project(text, n_results=5)
    if not hits:
        return ScreeningResult(
            action="skip",
            confidence=0,
            skip_reason="No vector matches found",
            review_reason=None,
            is_hourly=_detect_hourly(text),
            currency=_detect_currency(text),
        )

    best = hits[0]
    confidence = int(round(best["similarity"] * 100))
    confidence = max(0, min(100, confidence))
    label = best.get("label") or "guide match"
    is_hourly = _detect_hourly(text)
    currency = _detect_currency(text)

    if confidence < SKIP_THRESHOLD:
        return ScreeningResult(
            action="skip",
            confidence=confidence,
            skip_reason=f"Vector match {confidence}% — below {SKIP_THRESHOLD}%",
            review_reason=None,
            is_hourly=is_hourly,
            currency=currency,
        )

    threshold = settings.auto_bid_confidence_threshold
    if confidence >= threshold:
        review_reason = f"Strong vector match ({confidence}%) — {label}"
    else:
        review_reason = f"Moderate vector match ({confidence}%) — {label}; needs review"

    return ScreeningResult(
        action="bid",
        confidence=confidence,
        skip_reason=None,
        review_reason=review_reason,
        is_hourly=is_hourly,
        currency=currency,
    )


async def vector_screen_project_async(project_text: str) -> ScreeningResult:
    """Prefer PC chroma embeddings when this host only has lean TF-IDF."""
    text = project_text.strip()
    rejected = _quick_reject(text)
    if rejected:
        return rejected

    # Local chroma is authoritative.
    if chroma_available() and collection_count() > 0:
        return vector_screen_project(text)

    # Lean VPS → offload to PC worker when it has a chroma index.
    if backend_name() == "lean" and settings.queue_heavy_work:
        from app.database import SessionLocal
        from app.worker.queue import (
            JOB_VECTOR_SCREEN,
            enqueue_work,
            queue_heavy_enabled,
            wait_for_work_job,
            worker_status,
        )

        if queue_heavy_enabled():
            db = SessionLocal()
            try:
                st = worker_status(db)
                if st.get("worker_online") and st.get("worker_rag_chroma"):
                    entity_id = int(hashlib.sha1(text.encode("utf-8")).hexdigest()[:8], 16) % (2**31 - 1)
                    row = enqueue_work(
                        db,
                        JOB_VECTOR_SCREEN,
                        entity_id,
                        extra={"text": text},
                        dedupe=True,
                    )
                    job_id = row.id
                else:
                    job_id = None
                    logger.warning(
                        "PC chroma worker unavailable (online=%s chroma=%s) — lean TF-IDF fallback",
                        st.get("worker_online"),
                        st.get("worker_rag_chroma"),
                    )
            finally:
                db.close()

            if job_id is not None:
                try:
                    data = await wait_for_work_job(job_id, timeout_seconds=90.0)
                    result = _result_from_dict(data, text)
                    # Annotate that PC chroma scored this
                    if result.review_reason and "(pc chroma)" not in result.review_reason.lower():
                        result.review_reason = f"{result.review_reason} (PC chroma)"
                    elif result.skip_reason and "(pc chroma)" not in result.skip_reason.lower():
                        result.skip_reason = f"{result.skip_reason} (PC chroma)"
                    logger.info(
                        "PC chroma screen: action=%s confidence=%s",
                        result.action,
                        result.confidence,
                    )
                    return result
                except Exception:
                    logger.exception("PC chroma vector screen failed — lean fallback")

    return vector_screen_project(text)


def index_status() -> dict:
    meta = read_index_meta()
    chunks = collection_count()
    return {
        "ready": chunks > 0,
        "chunks": chunks,
        "backend": backend_name(),
        "indexed_at": meta.get("indexed_at"),
        "guide_chunks": meta.get("guide"),
        "cv_chunks": meta.get("cv"),
        "auto_bid_threshold": settings.auto_bid_confidence_threshold,
        "skip_threshold": SKIP_THRESHOLD,
        "prefer_pc_chroma": backend_name() == "lean" and bool(settings.queue_heavy_work),
    }
