from sqlalchemy.orm import Session

from app.config import settings


def apply_persisted_settings(db: Session) -> None:
    from app.database import AppSettings

    rows = db.query(AppSettings).all()
    for row in rows:
        if row.key in ("ai_provider", "ai_screening_provider", "ai_proposal_provider"):
            setattr(settings, row.key, "codex")
        elif row.key == "codex_model":
            settings.codex_model = row.value
        elif row.key == "automation_enabled":
            settings.automation_enabled = row.value.lower() in ("1", "true", "yes")
        elif row.key == "freelancer_bidding_enabled":
            settings.freelancer_bidding_enabled = row.value.lower() in ("1", "true", "yes")
        elif row.key == "auto_bid_confidence_threshold":
            settings.auto_bid_confidence_threshold = int(row.value)
        elif row.key == "max_bids_per_day":
            settings.max_bids_per_day = int(row.value)
        elif row.key == "test_mode":
            settings.test_mode = row.value.lower() in ("1", "true", "yes")

    # Plan prices + card-to-card details (admin-editable)
    from app.billing.commerce import apply_commerce_on_startup

    apply_commerce_on_startup(db)


def persist_setting(db: Session, key: str, value: str) -> None:
    from app.database import AppSettings

    if key in ("ai_provider", "ai_screening_provider", "ai_proposal_provider"):
        if value != "codex":
            raise ValueError("Only Codex is supported")
    if key.endswith("_api_key"):
        raise ValueError("AI API keys are retired; use codex login on the PC")
    row = db.get(AppSettings, key)
    if row:
        row.value = value
    else:
        db.add(AppSettings(key=key, value=value))
    db.commit()
