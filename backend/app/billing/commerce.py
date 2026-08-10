"""Runtime-editable plan prices + card-to-card details (DB-backed)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal

# AppSettings keys
KEY_CURRENCY = "plan_currency"
KEY_PRICE_1 = "plan_price_1_month"
KEY_PRICE_3 = "plan_price_3_month"
KEY_PRICE_6 = "plan_price_6_month"
KEY_PRICE_12 = "plan_price_12_month"
KEY_AI = "plan_ai_addon_per_month"
KEY_ATS = "plan_ats_addon_per_month"
KEY_CARD_NUMBER = "payment_card_number"
KEY_CARD_HOLDER = "payment_card_holder"
KEY_BANK_NAME = "payment_bank_name"
KEY_EXTRA_NOTE = "payment_extra_note"

_PRICE_KEYS = {
    KEY_PRICE_1: "plan_price_1_month",
    KEY_PRICE_3: "plan_price_3_month",
    KEY_PRICE_6: "plan_price_6_month",
    KEY_PRICE_12: "plan_price_12_month",
    KEY_AI: "plan_ai_addon_per_month",
    KEY_ATS: "plan_ats_addon_per_month",
}


@dataclass
class CommerceSettings:
    currency: str
    price_1_month: float
    price_3_month: float
    price_6_month: float
    price_12_month: float
    ai_addon_per_month: float
    ats_addon_per_month: float
    card_number: str
    card_holder: str
    bank_name: str
    extra_note: str


def _defaults() -> CommerceSettings:
    return CommerceSettings(
        currency=(settings.plan_currency or "USD").strip().upper() or "USD",
        price_1_month=float(settings.plan_price_1_month),
        price_3_month=float(settings.plan_price_3_month),
        price_6_month=float(settings.plan_price_6_month),
        price_12_month=float(settings.plan_price_12_month),
        ai_addon_per_month=float(settings.plan_ai_addon_per_month),
        ats_addon_per_month=float(settings.plan_ats_addon_per_month),
        card_number=(settings.payment_card_number or "").strip(),
        card_holder=(settings.payment_card_holder or "").strip(),
        bank_name=(settings.payment_bank_name or "").strip(),
        extra_note=(settings.payment_extra_note or "").strip(),
    )


def _apply_to_runtime(c: CommerceSettings) -> None:
    settings.plan_currency = c.currency
    settings.plan_price_1_month = c.price_1_month
    settings.plan_price_3_month = c.price_3_month
    settings.plan_price_6_month = c.price_6_month
    settings.plan_price_12_month = c.price_12_month
    settings.plan_ai_addon_per_month = c.ai_addon_per_month
    settings.plan_ats_addon_per_month = c.ats_addon_per_month
    settings.payment_card_number = c.card_number
    settings.payment_card_holder = c.card_holder
    settings.payment_bank_name = c.bank_name
    settings.payment_extra_note = c.extra_note


def load_commerce(db: Session | None = None) -> CommerceSettings:
    """Load commerce settings: DB overrides env defaults."""
    own = db is None
    if own:
        db = SessionLocal()
    try:
        from app.database import AppSettings

        c = _defaults()
        rows = {
            r.key: r.value
            for r in db.query(AppSettings)
            .filter(
                AppSettings.key.in_(
                    [
                        KEY_CURRENCY,
                        KEY_PRICE_1,
                        KEY_PRICE_3,
                        KEY_PRICE_6,
                        KEY_PRICE_12,
                        KEY_AI,
                        KEY_ATS,
                        KEY_CARD_NUMBER,
                        KEY_CARD_HOLDER,
                        KEY_BANK_NAME,
                        KEY_EXTRA_NOTE,
                    ]
                )
            )
            .all()
        }

        def _f(key: str, current: float) -> float:
            raw = (rows.get(key) or "").strip()
            if not raw:
                return current
            return float(raw)

        def _s(key: str, current: str) -> str:
            if key not in rows:
                return current
            return (rows.get(key) or "").strip()

        c.currency = _s(KEY_CURRENCY, c.currency).upper() or c.currency
        c.price_1_month = _f(KEY_PRICE_1, c.price_1_month)
        c.price_3_month = _f(KEY_PRICE_3, c.price_3_month)
        c.price_6_month = _f(KEY_PRICE_6, c.price_6_month)
        c.price_12_month = _f(KEY_PRICE_12, c.price_12_month)
        c.ai_addon_per_month = _f(KEY_AI, c.ai_addon_per_month)
        c.ats_addon_per_month = _f(KEY_ATS, c.ats_addon_per_month)
        c.card_number = _s(KEY_CARD_NUMBER, c.card_number)
        c.card_holder = _s(KEY_CARD_HOLDER, c.card_holder)
        c.bank_name = _s(KEY_BANK_NAME, c.bank_name)
        c.extra_note = _s(KEY_EXTRA_NOTE, c.extra_note)
        _apply_to_runtime(c)
        return c
    finally:
        if own:
            db.close()


def save_commerce_field(db: Session, key: str, value: str) -> CommerceSettings:
    """Persist one commerce field and refresh runtime settings."""
    from app.services.settings_service import persist_setting

    allowed = {
        KEY_CURRENCY,
        KEY_PRICE_1,
        KEY_PRICE_3,
        KEY_PRICE_6,
        KEY_PRICE_12,
        KEY_AI,
        KEY_ATS,
        KEY_CARD_NUMBER,
        KEY_CARD_HOLDER,
        KEY_BANK_NAME,
        KEY_EXTRA_NOTE,
    }
    if key not in allowed:
        raise ValueError(f"Unknown commerce key: {key}")

    if key in _PRICE_KEYS or key == KEY_CURRENCY:
        if key != KEY_CURRENCY:
            float(value)  # validate
        persist_setting(db, key, str(value).strip())
    else:
        persist_setting(db, key, str(value).strip())

    return load_commerce(db)


def apply_commerce_on_startup(db: Session) -> None:
    load_commerce(db)
