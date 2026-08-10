"""Persist global pre-match filter settings (both intake flows)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from sqlalchemy.orm import Session

from app.database import AppSettings
from app.filters.default_block_phrases import DEFAULT_BLOCK_PHRASES

SETTINGS_KEY = "pre_match_filters"


@dataclass
class PreMatchFilterSettings:
    enabled: bool = True
    block_phrases: list[str] = field(default_factory=lambda: list(DEFAULT_BLOCK_PHRASES))
    require_english: bool = True
    min_hourly_rate: float = 15.0
    max_fixed_budget: float = 2000.0

    def normalized_block_phrases(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for phrase in self.block_phrases:
            cleaned = phrase.strip()
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(cleaned)
        return out


def default_pre_match_filters() -> PreMatchFilterSettings:
    return PreMatchFilterSettings()


def load_pre_match_filters(db: Session) -> PreMatchFilterSettings:
    row = db.get(AppSettings, SETTINGS_KEY)
    if not row or not row.value.strip():
        return default_pre_match_filters()
    try:
        data = json.loads(row.value)
        base = asdict(default_pre_match_filters())
        base.update({k: v for k, v in data.items() if k in base})
        settings = PreMatchFilterSettings(**base)
        settings.block_phrases = settings.normalized_block_phrases()
        return settings
    except (json.JSONDecodeError, TypeError):
        return default_pre_match_filters()


def save_pre_match_filters(db: Session, settings: PreMatchFilterSettings) -> None:
    row = db.get(AppSettings, SETTINGS_KEY)
    settings.block_phrases = settings.normalized_block_phrases()
    payload = json.dumps(asdict(settings))
    if row:
        row.value = payload
    else:
        db.add(AppSettings(key=SETTINGS_KEY, value=payload))
    db.commit()
