"""Stage C — force Claim/Bridge JD spellings into Skills (merge into existing categories)."""

from __future__ import annotations

import re
from typing import Any

from app.ats.pipeline_v2.aliases import prefer_skills_category
from app.ats.pipeline_v2.evidence_match import contains_term
from app.ats.pipeline_v2.schema import KeywordLedger, KeywordTerm


def flatten_resume_text(resume: dict[str, Any]) -> str:
    parts: list[str] = [
        str(resume.get("summary") or ""),
        str(resume.get("professional_title") or ""),
    ]
    skills = resume.get("skills") or {}
    if isinstance(skills, dict):
        for cat, items in skills.items():
            parts.append(str(cat))
            parts.extend(str(x) for x in (items or []))
    elif isinstance(skills, list):
        parts.extend(str(x) for x in skills)
    for role in resume.get("experience") or []:
        parts.append(str(role.get("title") or ""))
        parts.append(str(role.get("company") or ""))
        parts.extend(str(b) for b in (role.get("bullets") or []))
    for proj in resume.get("projects") or []:
        parts.append(str(proj.get("name") or ""))
        parts.append(str(proj.get("subtitle") or ""))
        parts.extend(str(b) for b in (proj.get("bullets") or []))
    return "\n".join(parts)


def _skills_dict(resume: dict[str, Any]) -> dict[str, list[str]]:
    skills = resume.get("skills")
    if isinstance(skills, dict):
        out: dict[str, list[str]] = {}
        for cat, items in skills.items():
            out[str(cat)] = [str(x).strip() for x in (items or []) if str(x).strip()]
        return out
    if isinstance(skills, list):
        return {"Core Skills": [str(x).strip() for x in skills if str(x).strip()]}
    return {
        "AI & ML": [],
        "Development": [],
        "Frameworks & tools": [],
        "Focus areas": [],
    }


def _flatten_skills(skills: dict[str, list[str]]) -> str:
    parts: list[str] = []
    for cat, items in skills.items():
        parts.append(cat)
        parts.extend(items)
    return "\n".join(parts)


def _add_unique(items: list[str], term: str) -> bool:
    t = term.strip()
    if not t:
        return False
    if any(x.lower() == t.lower() for x in items):
        return False
    items.append(t)
    return True


def _category_for(term: KeywordTerm, skills: dict[str, list[str]]) -> str:
    existing = list(skills.keys())
    preferred = term.skills_category or prefer_skills_category(term.jd_term, existing)
    if preferred in skills:
        return preferred
    # case-insensitive match
    for cat in existing:
        if cat.lower() == preferred.lower():
            return cat
    # create preferred category name if empty resume skills
    if preferred not in skills:
        skills[preferred] = []
    return preferred


def hard_insert(resume: dict[str, Any], ledger: KeywordLedger) -> tuple[dict[str, Any], list[str]]:
    """Mutate resume so every Claim/Bridge skills term appears with JD spelling.

    Returns (resume, missing_claim_must_haves).
    """
    insert_log: list[dict[str, Any]] = []
    skills = _skills_dict(resume)
    text = flatten_resume_text({**resume, "skills": skills})

    targets = [t for t in ledger.terms if t.decision in ("Claim", "Bridge") and t.placements.skills]

    for t in targets:
        surface = (t.surface_forms.write_as or t.jd_term).strip()
        if not surface:
            continue
        skills_blob = _flatten_skills(skills)
        already_in_skills = contains_term(skills_blob, surface)
        already_in_resume = contains_term(text, surface)

        if already_in_skills:
            t.status.in_draft_skills = True
            continue

        # Alias-only in skills → still add exact JD spelling
        alias_only = any(contains_term(skills_blob, a) for a in (t.aliases or []))
        cat = _category_for(t, skills)
        if _add_unique(skills[cat], surface):
            t.status.in_draft_skills = True
            t.status.hard_insert_applied = True
            insert_log.append(
                {
                    "op": "skills_normalize" if alias_only else "skills_add",
                    "term": surface,
                    "category": cat,
                    "decision": t.decision,
                }
            )
        else:
            t.status.in_draft_skills = True

        if not already_in_resume and t.placements.summary and t.decision == "Claim":
            summary = str(resume.get("summary") or "").strip()
            if summary and not contains_term(summary, surface) and len(summary) < 560:
                # Light clause — avoid stuffing
                clause = f" Experienced with {surface}."
                if surface.lower() not in summary.lower():
                    resume["summary"] = (summary.rstrip(".") + "." + clause).strip()
                    t.status.in_draft_summary = True
                    t.status.hard_insert_applied = True
                    insert_log.append({"op": "summary_clause", "term": surface})

        # Refresh text after mutations
        text = flatten_resume_text({**resume, "skills": skills})

    # Optional bullet weave for Claim must-haves still absent from body (skills alone may score OK,
    # but bullets_min asks for presence in narrative when possible)
    for t in ledger.claim_must_haves():
        surface = (t.surface_forms.write_as or t.jd_term).strip()
        if not surface:
            continue
        body = flatten_resume_text({**resume, "skills": skills})
        # Count non-skills occurrences roughly
        skills_blob = _flatten_skills(skills)
        if contains_term(body, surface):
            # If only in skills, try one weave
            without_skills = body
            for cat, items in skills.items():
                without_skills = without_skills.replace(cat, " ")
                for item in items:
                    without_skills = without_skills.replace(item, " ")
            if contains_term(without_skills, surface):
                t.status.in_draft_bullets = max(t.status.in_draft_bullets, 1)
                continue
        if (t.placements.bullets_min or 0) <= 0:
            continue
        woven = _weave_into_best_bullet(resume, surface)
        if woven:
            t.status.in_draft_bullets = 1
            t.status.hard_insert_applied = True
            insert_log.append({"op": "bullet_weave", "term": surface, "target": woven})

    resume["skills"] = skills
    # Lock scored keywords to Claim+Bridge only
    resume["keywords_from_jd"] = ledger.scored_write_as()
    resume["keyword_ledger"] = {
        "version": ledger.version,
        "summary": ledger.summary,
        "scored_terms": ledger.scored_write_as(),
    }
    ledger.insert_log = insert_log

    text = flatten_resume_text(resume)
    missing = [
        t.jd_term
        for t in ledger.claim_must_haves()
        if not contains_term(text, t.surface_forms.write_as or t.jd_term)
    ]
    return resume, missing


def _weave_into_best_bullet(resume: dict[str, Any], surface: str) -> str | None:
    """Insert JD term into an existing related bullet without adding metrics."""
    surface_l = surface.lower()
    tokens = [
        tok
        for tok in re.findall(r"[a-z0-9+#.]{3,}", surface_l)
        if tok not in {"and", "the", "for", "with"}
    ]

    best: tuple[int, str, int, int] | None = None  # score, kind, block_idx, bullet_idx
    for kind, key in (("experience", "experience"), ("projects", "projects")):
        collection = resume.get(key) or []
        for idx, block in enumerate(collection):
            if not isinstance(block, dict):
                continue
            bullets = block.get("bullets") or []
            for bi, bullet in enumerate(bullets):
                b = str(bullet or "")
                if not b or contains_term(b, surface):
                    continue
                score = sum(1 for tok in tokens if tok in b.lower())
                if kind == "experience":
                    score += 1
                if best is None or score > best[0]:
                    best = (score, kind, idx, bi)

    if best is None:
        return None

    score, kind, idx, bi = best
    collection = resume.get(kind) or []
    if not isinstance(collection, list) or idx >= len(collection):
        return None
    block = collection[idx]
    bullets = list(block.get("bullets") or [])
    if bi >= len(bullets):
        return None

    if score <= 0:
        # Fallback: first experience bullet if short enough
        for eidx, eblock in enumerate(resume.get("experience") or []):
            if not isinstance(eblock, dict):
                continue
            ebullets = list(eblock.get("bullets") or [])
            if not ebullets:
                continue
            new_b = _inject(str(ebullets[0]), surface)
            if new_b and len(new_b.split()) <= 28:
                ebullets[0] = new_b
                eblock["bullets"] = ebullets
                return f"experience[{eidx}].bullets[0]"
            return None

    new_b = _inject(str(bullets[bi]), surface)
    if not new_b or len(new_b.split()) > 28:
        return None
    bullets[bi] = new_b
    block["bullets"] = bullets
    return f"{kind}[{idx}].bullets[{bi}]"


def _inject(bullet: str, surface: str) -> str | None:
    b = bullet.strip()
    if not b or contains_term(b, surface):
        return None
    # Prefer "… with X" / "… using X" patterns
    if re.search(r"\b(with|using|via)\b", b, re.I):
        # append near end before period
        if b.endswith("."):
            return f"{b[:-1]} and {surface}."
        return f"{b} using {surface}"
    if b.endswith("."):
        return f"{b[:-1]} with {surface}."
    return f"{b} with {surface}"
