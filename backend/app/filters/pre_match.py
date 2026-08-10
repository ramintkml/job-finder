"""Global pre-match filters applied before RAG screening (both intake flows)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.filters.budget_parse import (
    currency_allowed,
    parse_budget_from_api,
    parse_budget_from_text,
)
from app.filters.language_detect import check_english
from app.filters.pre_match_settings import PreMatchFilterSettings, load_pre_match_filters


def _project_text(text: str, project_data: dict[str, Any] | None) -> str:
    if project_data:
        title = str(project_data.get("title") or "")
        description = str(
            project_data.get("description") or project_data.get("preview_description") or ""
        )
        return f"{title}\n{description}\n{text}".strip()
    return text.strip()


def evaluate_pre_match(
    text: str,
    *,
    project_data: dict[str, Any] | None = None,
    settings: PreMatchFilterSettings | None = None,
    db: Session | None = None,
) -> tuple[bool, str]:
    """Return (accepted, skip_reason). accepted=False means filter out."""
    if settings is None:
        if db is None:
            from app.database import SessionLocal

            db = SessionLocal()
            try:
                settings = load_pre_match_filters(db)
            finally:
                db.close()
        else:
            settings = load_pre_match_filters(db)

    if not settings.enabled:
        return True, ""

    body = _project_text(text, project_data)
    lower = body.lower()

    for phrase in settings.normalized_block_phrases():
        if phrase.lower() in lower:
            return False, f"Blocked phrase: {phrase}"

    if settings.require_english:
        is_english, lang_detail = check_english(body)
        if not is_english:
            reason = "Language check failed (English required)"
            if lang_detail:
                reason = f"{reason}: {lang_detail}"
            return False, reason

    budget = (
        parse_budget_from_api(project_data)
        if project_data
        else parse_budget_from_text(body)
    )

    if not currency_allowed(budget.currency):
        found = budget.currency or "unknown"
        return False, f"Currency not allowed: {found} (allowed: USD, EUR, GBP, CAD, AUD, HKD)"

    if budget.is_hourly:
        floor = budget.hourly_floor
        if floor is not None and floor < settings.min_hourly_rate:
            return False, (
                f"Hourly rate ${floor:.0f} below minimum ${settings.min_hourly_rate:.0f}"
            )
    else:
        ceiling = budget.fixed_ceiling
        if ceiling is not None and ceiling > settings.max_fixed_budget:
            return False, (
                f"Fixed budget ${ceiling:.0f} above maximum ${settings.max_fixed_budget:.0f}"
            )

    return True, ""
