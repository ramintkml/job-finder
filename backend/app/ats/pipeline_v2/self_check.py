"""Pre-export self-check against the keyword ledger."""

from __future__ import annotations

from typing import Any

from app.ats.pipeline_v2.evidence_match import contains_term
from app.ats.pipeline_v2.hard_insert import flatten_resume_text
from app.ats.pipeline_v2.schema import KeywordLedger


def self_check(resume: dict[str, Any], ledger: KeywordLedger) -> dict[str, Any]:
    text = flatten_resume_text(resume)
    skills_blob = ""
    skills = resume.get("skills") or {}
    if isinstance(skills, dict):
        chunks: list[str] = []
        for cat, items in skills.items():
            chunks.append(str(cat))
            chunks.extend(str(x) for x in (items or []))
        skills_blob = "\n".join(chunks)
    elif isinstance(skills, list):
        skills_blob = "\n".join(str(x) for x in skills)

    missing_claim: list[str] = []
    omit_leaks: list[str] = []
    bridge_missing_skills: list[str] = []

    for t in ledger.terms:
        surface = (t.surface_forms.write_as or t.jd_term).strip()
        if not surface:
            continue
        if t.decision == "Omit":
            if contains_term(skills_blob, surface) or contains_term(text, surface):
                # Allow incidental English words that appear in base narrative only if
                # they weren't added as skill chips — still flag skill leaks.
                if contains_term(skills_blob, surface):
                    omit_leaks.append(surface)
            continue
        if t.decision in ("Claim", "Bridge") and t.placements.skills:
            if not contains_term(text, surface):
                if t.decision == "Claim":
                    missing_claim.append(surface)
                else:
                    bridge_missing_skills.append(surface)

    ok = not missing_claim and not omit_leaks
    return {
        "ok": ok,
        "missing_claim": missing_claim,
        "omit_leaks": omit_leaks,
        "bridge_missing_skills": bridge_missing_skills,
    }
