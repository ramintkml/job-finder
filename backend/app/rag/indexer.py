"""Build the vector index from the proposal guide + CV."""

from __future__ import annotations

import logging

from app.config import CV_MD_PATH, GUIDE_PATH
from app.rag.chunks import chunk_cv, chunk_proposal_guide
from app.rag.store import clear_collection, read_index_meta, upsert_chunks, write_index_meta

logger = logging.getLogger(__name__)


async def build_profile_index() -> dict:
    """Rebuild vector index from data/proposal_guide.md and data/cv/*.md."""
    if not GUIDE_PATH.is_file():
        raise ValueError("Proposal guide not found — create data/proposal_guide.md first.")

    guide_text = GUIDE_PATH.read_text(encoding="utf-8")
    guide_chunks = chunk_proposal_guide(guide_text)
    if not guide_chunks:
        raise ValueError(
            "Proposal guide is empty or has no indexable sections. Add ## headings with content."
        )

    cv_chunks = chunk_cv()
    if not CV_MD_PATH.is_file():
        logger.warning("CV not found at %s — indexing guide only", CV_MD_PATH)
    elif not cv_chunks:
        logger.warning("CV found but produced no indexable chunks: %s", CV_MD_PATH)

    all_chunks = guide_chunks + cv_chunks
    clear_collection()
    total = upsert_chunks(all_chunks)
    if total <= 0:
        raise RuntimeError(
            "Index build stored 0 chunks — vector backend failed. "
            "On a lean VPS this should use the pure-Python TF-IDF fallback; check server logs."
        )
    write_index_meta(
        chunk_count=total,
        guide_count=len(guide_chunks),
        cv_count=len(cv_chunks),
    )
    logger.info(
        "RAG index built: %s guide + %s CV = %s chunks",
        len(guide_chunks),
        len(cv_chunks),
        total,
    )
    from app.rag.store import backend_name

    return {
        "ok": True,
        "chunks": total,
        "guide_chunks": len(guide_chunks),
        "cv_chunks": len(cv_chunks),
        "backend": backend_name(),
        "indexed_at": read_index_meta().get("indexed_at"),
    }
