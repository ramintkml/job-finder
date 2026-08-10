from sqlalchemy.orm import Session

from app.config import settings


def apply_persisted_settings(db: Session) -> None:
    from app.database import AppSettings

    rows = db.query(AppSettings).all()
    for row in rows:
        if row.key == "ai_provider":
            settings.ai_provider = row.value
        elif row.key == "ai_model":
            settings.ai_model = row.value
        elif row.key == "ai_screening_provider":
            settings.ai_screening_provider = row.value
        elif row.key == "ai_screening_model":
            settings.ai_screening_model = row.value
        elif row.key == "ai_proposal_provider":
            settings.ai_proposal_provider = row.value
        elif row.key == "ai_proposal_model":
            settings.ai_proposal_model = row.value
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
        elif row.key == "groq_api_key" and row.value:
            settings.groq_api_key = row.value
        elif row.key == "gemini_api_key" and row.value:
            settings.gemini_api_key = row.value
        elif row.key == "deepseek_api_key" and row.value:
            settings.deepseek_api_key = row.value
        elif row.key == "anthropic_api_key" and row.value:
            settings.anthropic_api_key = row.value
        elif row.key == "openai_api_key" and row.value:
            settings.openai_api_key = row.value

    # Plan prices + card-to-card details (admin-editable)
    from app.billing.commerce import apply_commerce_on_startup

    apply_commerce_on_startup(db)


def persist_setting(db: Session, key: str, value: str) -> None:
    from app.database import AppSettings

    row = db.get(AppSettings, key)
    if row:
        row.value = value
    else:
        db.add(AppSettings(key=key, value=value))
    db.commit()
