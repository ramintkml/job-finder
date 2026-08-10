"""Build a frozen KeywordLedger from JD + base CV."""

from __future__ import annotations

import logging
from typing import Any

from app.ats.pipeline_v2.aliases import aliases_for, prefer_skills_category
from app.ats.pipeline_v2.evidence_match import classify_term
from app.ats.pipeline_v2.schema import (
    KeywordLedger,
    KeywordTerm,
    SurfaceForms,
    TermPlacements,
    TermStatus,
    term_id,
    utc_now_iso,
)

logger = logging.getLogger(__name__)


async def build_ledger(
    *,
    base_cv: str,
    description: str,
    title: str = "",
    company: str = "",
    job_url: str = "",
    existing_skill_categories: list[str] | None = None,
) -> KeywordLedger:
    from app.ats.keywords import extract_jd_keywords_hybrid

    hybrid = await extract_jd_keywords_hybrid(
        description,
        base_cv=base_cv,
        title=title,
    )
    must = [str(x).strip() for x in (hybrid.get("must_have") or []) if str(x).strip()]
    nice = [str(x).strip() for x in (hybrid.get("nice_to_have") or []) if str(x).strip()]
    all_kw = [str(x).strip() for x in (hybrid.get("all") or []) if str(x).strip()]

    must_set = {m.lower() for m in must}
    nice_set = {n.lower() for n in nice}

    # Union ordered: must, nice, then remaining all
    ordered: list[str] = []
    seen: set[str] = set()
    for bucket in (must, nice, all_kw):
        for kw in bucket:
            key = kw.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(kw)
    ordered = ordered[:40]

    terms: list[KeywordTerm] = []
    for kw in ordered:
        key = kw.lower()
        if key in must_set:
            priority = "must_have"
        elif key in nice_set:
            priority = "nice_to_have"
        else:
            priority = "inferred"

        classified = classify_term(
            kw,
            base_text=base_cv,
            priority=priority,
            must_set=must_set,
        )
        decision = classified["decision"]
        write_as = kw  # exact JD spelling preserved from extractor when possible

        placements = TermPlacements(
            skills=decision in ("Claim", "Bridge"),
            summary=decision == "Claim" and priority == "must_have",
            bullets_min=1 if decision == "Claim" and priority == "must_have" else 0,
            bullets_max=2,
        )
        cat = prefer_skills_category(kw, existing_skill_categories)
        term = KeywordTerm(
            id=term_id(kw),
            jd_term=kw,
            priority=priority,  # type: ignore[arg-type]
            aliases=aliases_for(kw),
            decision=decision,  # type: ignore[arg-type]
            confidence=float(classified.get("confidence") or 0),
            evidence=classified["evidence"],
            bridge_phrase=classified.get("bridge_phrase"),
            omit_reason=classified.get("omit_reason"),
            placements=placements,
            surface_forms=SurfaceForms(
                write_as=write_as,
                skills_as=write_as,
                allowed_extra=aliases_for(kw)[:6],
            ),
            status=TermStatus(),
            skills_category=cat,
        )
        terms.append(term)

    claim_n = sum(1 for t in terms if t.decision == "Claim")
    bridge_n = sum(1 for t in terms if t.decision == "Bridge")
    omit_n = sum(1 for t in terms if t.decision == "Omit")
    flag_n = sum(1 for t in terms if t.decision == "Flag")
    must_claimable = sum(
        1 for t in terms if t.priority == "must_have" and t.decision in ("Claim", "Bridge")
    )
    must_missing = sum(
        1 for t in terms if t.priority == "must_have" and t.decision == "Omit"
    )

    skills_must = [
        t.surface_forms.write_as
        for t in terms
        if t.decision in ("Claim", "Bridge") and t.placements.skills
    ]
    summary_prefer = [
        t.surface_forms.write_as
        for t in terms
        if t.decision == "Claim" and t.placements.summary
    ][:10]

    ledger = KeywordLedger(
        version="2.0",
        job={"title": title or "", "company": company or "", "url": job_url or ""},
        generated_at=utc_now_iso(),
        source={
            "base_cv_chars": len(base_cv or ""),
            "jd_chars": len(description or ""),
            "extractor": "hybrid_v2",
            "hybrid": {
                "must_have": must[:25],
                "nice_to_have": nice[:15],
            },
        },
        terms=terms,
        summary={
            "claim_count": claim_n,
            "bridge_count": bridge_n,
            "omit_count": omit_n,
            "flag_count": flag_n,
            "must_have_claimable": must_claimable,
            "must_have_missing": must_missing,
        },
        placement_plan={
            "skills_must_include": skills_must,
            "summary_prefer": summary_prefer,
            "bullet_tags": [],
        },
    )
    return ledger


def ledger_prompt_block(ledger: KeywordLedger) -> str:
    """Compact instructions for the AI writer."""
    claim = [t for t in ledger.terms if t.decision == "Claim"]
    bridge = [t for t in ledger.terms if t.decision == "Bridge"]
    omit = [t for t in ledger.terms if t.decision == "Omit"]

    def fmt(terms: list[KeywordTerm], limit: int = 25) -> str:
        parts = []
        for t in terms[:limit]:
            bit = t.surface_forms.write_as or t.jd_term
            if t.bridge_phrase:
                bit += f" [bridge: {t.bridge_phrase}]"
            parts.append(bit)
        return ", ".join(parts) if parts else "—"

    return f"""
KEYWORD LEDGER v2 (LOCKED — obey exactly):
- Claim (write EXACT spelling in Skills; weave into Summary/bullets): {fmt(claim)}
- Bridge (also put JD spelling in Skills; bullets may use bridge phrase): {fmt(bridge)}
- Omit (NEVER invent / never list): {fmt(omit, 20)}
- keywords_from_jd MUST be exactly the Claim+Bridge write_as list (for scoring).
- Do not drop Claim terms. Prefer JD spelling over aliases (e.g. write "machine learning" not only "ML").
"""
