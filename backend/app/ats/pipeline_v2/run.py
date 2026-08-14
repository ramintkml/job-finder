"""Orchestrate ATS pipeline v2: ledger → AI write → hard_insert → self_check."""

from __future__ import annotations

import logging
from typing import Any

from app.ai.evaluator import _call_ai, _extract_json
from app.ats.guide import load_ats_guide
from app.ats.pipeline_v2.hard_insert import hard_insert
from app.ats.pipeline_v2.ledger import build_ledger, ledger_prompt_block
from app.ats.pipeline_v2.self_check import self_check
from app.ats.selected_projects import ensure_selected_projects, project_markdown_rules
from app.ats.tips import format_guidance_for_tailor
from app.config import settings

logger = logging.getLogger(__name__)


async def run_pipeline_v2(
    *,
    base_cv: str,
    title: str,
    description: str,
    company: str = "",
    location: str = "",
    job_url: str = "",
    prior_tips: dict | None = None,
    prior_scoring: dict | None = None,
) -> dict[str, Any]:
    """Return structured resume dict with keywords_from_jd = Claim+Bridge only."""
    base_cv = (base_cv or "").strip()
    description = (description or "").strip()
    if len(base_cv) < 40:
        raise ValueError("Base CV is too short")
    if len(description) < 40:
        raise ValueError("Job description is too short")

    # Seed categories from base CV heuristics for better merge targets
    existing_cats = _guess_categories_from_base(base_cv)

    ledger = await build_ledger(
        base_cv=base_cv,
        description=description,
        title=title,
        company=company,
        job_url=job_url,
        existing_skill_categories=existing_cats,
    )

    guide = load_ats_guide()
    guidance = format_guidance_for_tailor(prior_tips, prior_scoring)
    guidance_block = f"\n\n{guidance}\n" if guidance else ""
    ledger_block = ledger_prompt_block(ledger)

    system = (
        "You are an ATS resume writer for pipeline v2. "
        "The KEYWORD LEDGER is locked: write every Claim and Bridge term using EXACT JD spelling "
        "in the Skills section (merged into existing categories). "
        "Never invent employers, degrees, dates, metrics, or Omit tools. "
        "Return exactly one JSON object."
    )
    user = f"""ATS GUIDE v2.0 (truthfulness + formatting):
{guide[:16000]}

BASE CV (source of truth):
{base_cv[:12000]}

TARGET JOB:
Title: {title or 'Role'}
Company: {company}
Location: {location}
URL: {job_url}
Description:
{description[:6000]}
{ledger_block}{guidance_block}
{project_markdown_rules()}
Return JSON with this shape (Ramin Takmil CV template — keep this section order):
{{
  "full_name": "...",
  "professional_title": "...",
  "email": "...",
  "phone": "...",
  "linkedin": "...",
  "github": "...",
  "portfolio": "",
  "location": "City/Country or Remote",
  "summary": "3-5 lines tailored to the role; include top Claim must-have JD spellings naturally",
  "skills": {{
    "AI & ML": ["..."],
    "Development": ["..."],
    "Frameworks & tools": ["..."],
    "Focus areas": ["..."]
  }},
    "projects": [
    {{
      "name": "canonical project name",
      "subtitle": "",
      "url": "github and/or live URL — required",
      "bullets": ["Action Verb + JD-aligned tech + truthful result", "..."]
    }}
  ],
  "additional_experience": [
    {{"title": "Short theme label", "text": "1-2 sentence truthful block"}}
  ],
  "experience": [
    {{
      "title": "...",
      "company": "...",
      "location": "optional",
      "dates": "YYYY – Present|YYYY",
      "bullets": ["Action Verb + Technology + Measurable Result", ...]
    }}
  ],
  "research": "optional short research/thesis blurb or empty string",
  "education": [
    {{"degree": "...", "school": "...", "dates": "...", "gpa": "optional"}}
  ],
  "languages": ["English: IELTS ..."],
  "certifications": ["..."],
  "keywords_from_jd": ["Claim+Bridge exact spellings only"],
  "diff_summary": "2-4 sentences on what changed vs the base CV for this job"
}}
Omit empty optional sections rather than inventing content.
"""
    raw = await _call_ai(
        system,
        user,
        provider=settings.proposal_provider,
        model=settings.proposal_model(),
        max_tokens=4096,
    )
    data = _extract_json(raw)
    if not isinstance(data, dict):
        raise ValueError("AI resume tailor returned non-object JSON")
    if not (data.get("full_name") or "").strip():
        raise ValueError("AI resume missing full_name")
    if not data.get("experience") and not data.get("projects"):
        raise ValueError("AI resume missing experience and projects")

    # Stage C
    data, missing = hard_insert(data, ledger)
    check = self_check(data, ledger)
    if missing or not check.get("ok"):
        # Second hard-insert pass after normalizing skills categories
        data, missing = hard_insert(data, ledger)
        check = self_check(data, ledger)

    data = ensure_selected_projects(
        data, job_text=f"{title}\n{company}\n{description}"
    )

    data["keywords_from_jd"] = ledger.scored_write_as()
    data["_pipeline_v2"] = {
        "ledger_summary": ledger.summary,
        "insert_log": ledger.insert_log,
        "self_check": check,
        "missing_claim_after_insert": missing,
        "scored_terms": ledger.scored_write_as(),
    }
    # Keep a compact ledger on the resume for persistence/debug (not for DOCX)
    data["_keyword_ledger"] = ledger.to_dict()
    return data


def _guess_categories_from_base(base_cv: str) -> list[str]:
    lower = (base_cv or "").lower()
    cats = []
    if "ai & ml" in lower or "machine learning" in lower or "deep learning" in lower:
        cats.append("AI & ML")
    if "development" in lower or "python" in lower:
        cats.append("Development")
    if "frameworks" in lower or "docker" in lower or "git" in lower:
        cats.append("Frameworks & tools")
    if "focus" in lower:
        cats.append("Focus areas")
    return cats or ["AI & ML", "Development", "Frameworks & tools", "Focus areas"]
