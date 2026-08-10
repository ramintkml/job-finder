"""AI relevance check for LinkedIn jobs before sending application emails."""

from __future__ import annotations

from dataclasses import dataclass

from app.ai.evaluator import (
    _call_ai,
    _confidence_from_json,
    _extract_json,
    _load_screening_context,
    load_guide,
)
from app.config import settings
from app.linkedin.email_compose import _brief_applicant_profile, _brief_job_summary
from app.linkedin.settings import LinkedInSettings

LINKEDIN_SCREENING_JSON = (
    'Return exactly one JSON object with keys: action, confidence, skip_reason, review_reason. '
    'action must be "send" or "skip". Example: '
    '{"action":"send","confidence":82,"skip_reason":null,"review_reason":"Strong Python/AI fit"}'
)


@dataclass
class LinkedInScreeningResult:
    action: str  # send | skip
    confidence: int
    skip_reason: str | None
    review_reason: str | None


def _parse_linkedin_screening(data: dict) -> LinkedInScreeningResult:
    action = str(data.get("action") or "skip").lower().strip()
    if action not in ("send", "skip"):
        action = "skip"
    confidence = _confidence_from_json(data)
    skip_reason = data.get("skip_reason")
    review_reason = data.get("review_reason")

    if action == "skip":
        return LinkedInScreeningResult(
            action="skip",
            confidence=confidence,
            skip_reason=str(skip_reason).strip() if skip_reason else "Not a relevant fit",
            review_reason=None,
        )

    return LinkedInScreeningResult(
        action="send",
        confidence=confidence,
        skip_reason=None,
        review_reason=str(review_reason).strip() if review_reason else None,
    )


async def ai_screen_linkedin_job(job: dict, cfg: LinkedInSettings) -> LinkedInScreeningResult:
    """Review brief job details vs applicant profile; skip irrelevant roles before emailing."""
    guide = load_guide()
    context = _load_screening_context(guide)
    system = (
        "You screen LinkedIn job postings before the applicant sends a cold application email. "
        "Use the applicant profile and screening rules. "
        "Send only when the role clearly matches their skills and experience. "
        "Skip unrelated roles, wrong seniority, unrelated industries, pure sales/non-tech, "
        "or jobs that contradict the filtering rules. "
        "Respond with valid JSON only — no markdown fences, no extra text."
    )
    user = (
        f"{context}\n\n---\n\n"
        f"Applicant profile:\n{_brief_applicant_profile(cfg)}\n\n"
        f"Job (brief):\n{_brief_job_summary(job)}\n\n"
        f"{LINKEDIN_SCREENING_JSON}"
    )
    raw = await _call_ai(
        system,
        user,
        provider=settings.screening_provider,
        model=settings.screening_model(),
        max_tokens=384,
    )
    return _parse_linkedin_screening(_extract_json(raw))
