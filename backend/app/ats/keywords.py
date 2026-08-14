"""Hybrid JD keyword extraction: AI phrases + heuristic tokens."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.ats.score import extract_jd_keywords, _is_junk_keyword, keyword_in_text

logger = logging.getLogger(__name__)


async def extract_jd_keywords_hybrid(
    job_description: str,
    *,
    base_cv: str = "",
    title: str = "",
) -> dict[str, Any]:
    """Return must-have / nice-to-have / all keywords for ATS + resume targeting.

    Hybrid method:
    1) Heuristic token extraction (stable, exact spellings)
    2) AI phrase extraction (multi-word must-haves)
    3) Merge + dedupe (case-insensitive)
    4) Optional Claim split vs base CV (substring match)
    """
    jd = (job_description or "").strip()
    heuristic = extract_jd_keywords(jd, None)

    ai_must: list[str] = []
    ai_nice: list[str] = []
    try:
        from app.ai.evaluator import _call_ai, _extract_json
        from app.config import settings

        system = (
            "Extract ATS keywords from a job description. "
            "Return JSON only. Prefer exact spellings from the JD. "
            "Do not invent tools not mentioned. Keep items short (1-4 words)."
        )
        user = f"""Job title: {title or 'Role'}

Job description:
{jd[:8000]}

Return JSON:
{{
  "must_have": ["required skills/tools/phrases"],
  "nice_to_have": ["optional skills/tools/phrases"]
}}
Max 25 must_have and 15 nice_to_have.
"""
        raw = await _call_ai(
            system,
            user,
            provider=settings.proposal_provider,
            model=settings.proposal_model(),
            max_tokens=1200,
        )
        data = _extract_json(raw)
        if isinstance(data, dict):
            ai_must = [str(x).strip() for x in (data.get("must_have") or []) if str(x).strip()]
            ai_nice = [str(x).strip() for x in (data.get("nice_to_have") or []) if str(x).strip()]
    except Exception:
        logger.exception("AI keyword extraction failed; using heuristics only")

    all_keywords = [
        k for k in extract_jd_keywords(jd, ai_must + ai_nice + heuristic) if not _is_junk_keyword(k)
    ]

    cv_l = (base_cv or "").lower()
    claimable: list[str] = []
    missing: list[str] = []
    if cv_l:
        for kw in all_keywords:
            if kw.lower() in cv_l or _fuzzy_in_cv(kw, cv_l):
                claimable.append(kw)
            else:
                missing.append(kw)
    else:
        claimable = list(all_keywords)

    return {
        "must_have": _dedupe(ai_must)[:25],
        "nice_to_have": _dedupe(ai_nice)[:15],
        "all": all_keywords,
        "claimable": claimable[:40],
        "missing": missing[:40],
        "heuristic": heuristic,
    }


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _fuzzy_in_cv(keyword: str, cv_lower: str) -> bool:
    if _is_junk_keyword(keyword):
        return True
    return keyword_in_text(keyword, cv_lower)
