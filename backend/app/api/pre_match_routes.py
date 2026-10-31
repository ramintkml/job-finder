from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.filters.pre_match_settings import (
    PreMatchFilterSettings,
    load_pre_match_filters,
    save_pre_match_filters,
)

router = APIRouter(prefix="/pre-match-filters", tags=["pre-match-filters"])


class PreMatchFiltersIn(BaseModel):
    enabled: bool = True
    block_phrases: list[str] = Field(default_factory=list)
    require_english: bool = True
    min_hourly_rate: float = Field(default=15.0, ge=0)
    max_fixed_budget: float = Field(default=2000.0, ge=0)


@router.get("")
def get_pre_match_filters(db: Session = Depends(get_db)):
    settings = load_pre_match_filters(db)
    return {"ok": True, "filters": settings.__dict__}


@router.put("")
def update_pre_match_filters(body: PreMatchFiltersIn, db: Session = Depends(get_db)):
    settings = PreMatchFilterSettings(
        enabled=body.enabled,
        block_phrases=body.block_phrases,
        require_english=body.require_english,
        min_hourly_rate=body.min_hourly_rate,
        max_fixed_budget=body.max_fixed_budget,
    )
    save_pre_match_filters(db, settings)
    return {"ok": True, "filters": settings.__dict__}
