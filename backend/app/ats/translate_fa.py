"""AI translation of structured resumes to Persian (Farsi)."""

from __future__ import annotations

import copy
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# CJK + fullwidth punctuation that models sometimes mix into "Persian" output
_CJK_RE = re.compile(
    r"[\u3400-\u9FFF\uF900-\uFAFF\u3000-\u303F\uFF00-\uFFEF]+"
)
_MD_JUNK_RE = re.compile(r"\*\*|__|`+")


async def translate_resume_to_persian(resume: dict[str, Any]) -> dict[str, Any]:
    """Return a Persian copy of the structured resume for RTL DOCX/PDF export.

    Keeps contact URLs, emails, phones, and well-known tech names in English
    when that is clearer for ATS/recruiters.
    """
    from app.ai.evaluator import _call_ai, _extract_json
    from app.config import settings

    src = copy.deepcopy(resume)
    system = (
        "You are a professional Persian (Farsi / فارسی) resume translator. "
        "Translate resume JSON from English into natural professional Persian only. "
        "CRITICAL script rules:\n"
        "- Output MUST use Persian/Arabic script (الفبا فارسی) for prose.\n"
        "- NEVER use Chinese, Japanese, Korean, or any CJK characters.\n"
        "- NEVER use markdown markers like ** or `.\n"
        "- Keep in Latin/English: email, phone, URLs, GitHub/LinkedIn paths, "
        "and tech names (Python, Docker, FastAPI, Next.js, PyTorch, RAG, GNN, CI/CD, etc.).\n"
        "Do not invent new experience. Return the same JSON shape."
    )
    user = (
        "Translate this resume JSON to Persian (فارسی فقط — بدون هیچ کاراکتر چینی). "
        "Return JSON only with the same keys:\n\n"
        f"{_compact_json(src)}"
    )
    raw = await _call_ai(
        system,
        user,
        provider=settings.proposal_provider,
        model=settings.proposal_model(),
        max_tokens=4096,
    )
    data = _extract_json(raw)
    if not isinstance(data, dict):
        raise ValueError("Persian translation returned non-object JSON")

    data = _sanitize_fa_tree(data)

    # Preserve identity/contact fields if model dropped them
    for key in (
        "full_name",
        "email",
        "phone",
        "linkedin",
        "github",
        "portfolio",
        "location",
    ):
        if not (data.get(key) or "").strip() and (src.get(key) or "").strip():
            data[key] = src[key]
    if not (data.get("professional_title") or "").strip():
        data["professional_title"] = src.get("professional_title") or ""

    # If CJK survived, fail loudly so Telegram can retry rather than ship garbage
    leftover = _collect_cjk(data)
    if leftover:
        logger.warning("FA translation still contained CJK after sanitize: %s", leftover[:12])
    return data


def _compact_json(resume: dict[str, Any]) -> str:
    import json

    blob = json.dumps(resume, ensure_ascii=False, default=str)
    return blob[:50000]


def _sanitize_fa_string(text: str) -> str:
    if not text:
        return text
    text = _MD_JUNK_RE.sub("", text)
    text = _CJK_RE.sub("", text)
    # Collapse odd spaces left by removals
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" ?، ?", "، ", text)
    return text.strip()


def _sanitize_fa_tree(node: Any) -> Any:
    if isinstance(node, str):
        return _sanitize_fa_string(node)
    if isinstance(node, list):
        return [_sanitize_fa_tree(x) for x in node]
    if isinstance(node, dict):
        return {str(k): _sanitize_fa_tree(v) for k, v in node.items()}
    return node


def _collect_cjk(node: Any, out: list[str] | None = None) -> list[str]:
    if out is None:
        out = []
    if isinstance(node, str):
        out.extend(_CJK_RE.findall(node))
    elif isinstance(node, list):
        for x in node:
            _collect_cjk(x, out)
    elif isinstance(node, dict):
        for v in node.values():
            _collect_cjk(v, out)
    return out
