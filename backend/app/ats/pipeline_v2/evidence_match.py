"""Find evidence snippets in base CV / profile text via exact + alias match."""

from __future__ import annotations

import re
from typing import Any

from app.ats.pipeline_v2.aliases import aliases_for
from app.ats.pipeline_v2.schema import EvidenceHit


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def contains_term(haystack: str, term: str) -> bool:
    """Boundary-aware case-insensitive contains."""
    h = normalize_ws(haystack).lower()
    t = normalize_ws(term).lower()
    if not h or not t:
        return False
    if t in h:
        # Prefer word-ish boundaries for short tokens
        if len(t) <= 3:
            return bool(re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", h))
        return True
    return False


def find_evidence(base_text: str, jd_term: str, *, window: int = 110) -> EvidenceHit | None:
    """Return first evidence hit for jd_term or any alias."""
    text = base_text or ""
    if not text.strip() or not (jd_term or "").strip():
        return None

    candidates = [jd_term.strip()] + aliases_for(jd_term)
    lower = text.lower()

    for cand in candidates:
        cand_l = cand.lower()
        if len(cand_l) <= 1:
            continue
        # Short tokens need boundaries
        if len(cand_l) <= 3:
            m = re.search(rf"(?<![a-z0-9]){re.escape(cand_l)}(?![a-z0-9])", lower)
            if not m:
                continue
            start, end = m.start(), m.end()
        else:
            start = lower.find(cand_l)
            if start < 0:
                continue
            end = start + len(cand_l)

        left = max(0, start - window)
        right = min(len(text), end + window)
        snippet = normalize_ws(text[left:right])
        via = "exact" if cand_l == jd_term.strip().lower() else f"alias:{cand}"
        return EvidenceHit(
            source="base_cv",
            snippet=snippet[:240],
            match_via=via,
            char_start=start,
            char_end=end,
        )
    return None


def classify_term(
    jd_term: str,
    *,
    base_text: str,
    priority: str,
    must_set: set[str],
) -> dict[str, Any]:
    """Rule-based Claim / Bridge / Omit (no AI required for v2 core)."""
    hit = find_evidence(base_text, jd_term)
    term_l = jd_term.strip().lower()

    # Soft bridge: related family present even if exact alias miss
    bridge = _bridge_hint(jd_term, base_text) if hit is None else None

    if hit is not None:
        return {
            "decision": "Claim",
            "confidence": 0.9 if hit.match_via == "exact" else 0.82,
            "evidence": hit,
            "bridge_phrase": None,
            "omit_reason": None,
        }
    if bridge:
        return {
            "decision": "Bridge",
            "confidence": 0.55,
            "evidence": bridge["evidence"],
            "bridge_phrase": bridge["phrase"],
            "omit_reason": None,
        }
    return {
        "decision": "Omit",
        "confidence": 0.8,
        "evidence": EvidenceHit(),
        "bridge_phrase": None,
        "omit_reason": "No supporting evidence in base CV/profile",
        "priority_note": "must_have" if term_l in must_set or priority == "must_have" else priority,
    }


def _bridge_hint(jd_term: str, base_text: str) -> dict[str, Any] | None:
    """Limited honest bridges — never invent vendors."""
    t = jd_term.lower()
    base_l = base_text.lower()
    rules: list[tuple[tuple[str, ...], str, str, str]] = [
        # (need any of these in CV, jd needles, bridge phrase, match label)
        (
            ("chromadb", "vector search", "rag"),
            "vector database|vector db|embeddings store",
            "Built retrieval / vector-search pipelines (e.g. ChromaDB)",
            "vector-search stack",
        ),
        (
            ("docker",),
            "container orchestration|kubernetes|k8s",
            "Deployed containerized services with Docker (not Kubernetes)",
            "docker-not-k8s",
        ),
        (
            ("git", "github"),
            "version control|source control",
            "Used Git/GitHub versioning across project repositories",
            "git-versioning",
        ),
    ]
    for cv_needles, jd_pat, phrase, label in rules:
        if not re.search(jd_pat, t):
            # also allow if jd_term itself is one of the targets
            if t not in jd_pat.replace("|", " ").split() and t not in (
                "kubernetes",
                "k8s",
                "vector database",
                "version control",
            ):
                continue
        if not any(n in base_l for n in cv_needles):
            continue
        # Find a snippet from the supporting needle
        for n in cv_needles:
            hit = find_evidence(base_text, n)
            if hit:
                hit.match_via = f"bridge:{label}"
                return {"phrase": phrase, "evidence": hit}
    return None
