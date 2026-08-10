"""User registration and subscription lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.billing.plans import PlanQuote, quote_plan
from app.database import Subscription, User


@dataclass(frozen=True)
class Entitlements:
    """What a user may use right now."""

    has_active_plan: bool
    include_ai: bool
    include_ats: bool
    months: int | None
    expires_at: datetime | None
    status: str  # none | pending | awaiting_confirm | active | expired | cancelled


def get_or_create_user(
    db: Session,
    *,
    telegram_user_id: int,
    chat_id: int,
    username: str | None = None,
    first_name: str | None = None,
) -> User:
    user = db.query(User).filter(User.telegram_user_id == telegram_user_id).one_or_none()
    now = datetime.now(timezone.utc)
    if user is None:
        user = User(
            telegram_user_id=telegram_user_id,
            chat_id=chat_id,
            username=(username or "")[:128] or None,
            first_name=(first_name or "")[:128] or None,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    changed = False
    if user.chat_id != chat_id:
        user.chat_id = chat_id
        changed = True
    if username is not None and user.username != username:
        user.username = username[:128] or None
        changed = True
    if first_name is not None and user.first_name != first_name:
        user.first_name = first_name[:128] or None
        changed = True
    if not user.is_active:
        user.is_active = True
        changed = True
    if changed:
        user.updated_at = now
        db.commit()
        db.refresh(user)
    return user


def get_user_by_telegram_id(db: Session, telegram_user_id: int) -> User | None:
    return db.query(User).filter(User.telegram_user_id == telegram_user_id).one_or_none()


def get_user_by_chat_id(db: Session, chat_id: int) -> User | None:
    return db.query(User).filter(User.chat_id == chat_id).one_or_none()


def get_active_subscription(db: Session, user_id: int) -> Subscription | None:
    now = datetime.now(timezone.utc)
    sub = (
        db.query(Subscription)
        .filter(
            Subscription.user_id == user_id,
            Subscription.status == "active",
        )
        .order_by(Subscription.expires_at.desc())
        .first()
    )
    if sub is None:
        return None
    exp = sub.expires_at
    if exp is not None and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp is not None and exp < now:
        sub.status = "expired"
        db.commit()
        return None
    return sub


def get_pending_subscription(db: Session, user_id: int) -> Subscription | None:
    """Open order waiting for card transfer and/or admin confirm."""
    return (
        db.query(Subscription)
        .filter(
            Subscription.user_id == user_id,
            Subscription.status.in_(("pending", "awaiting_confirm")),
        )
        .order_by(Subscription.created_at.desc())
        .first()
    )


def user_entitlements(db: Session, user_id: int) -> Entitlements:
    active = get_active_subscription(db, user_id)
    if active:
        return Entitlements(
            has_active_plan=True,
            include_ai=bool(active.include_ai),
            include_ats=bool(active.include_ats),
            months=int(active.months),
            expires_at=active.expires_at,
            status="active",
        )
    pending = get_pending_subscription(db, user_id)
    if pending:
        return Entitlements(
            has_active_plan=False,
            include_ai=bool(pending.include_ai),
            include_ats=bool(pending.include_ats),
            months=int(pending.months),
            expires_at=None,
            status=pending.status,  # pending | awaiting_confirm
        )
    return Entitlements(
        has_active_plan=False,
        include_ai=False,
        include_ats=False,
        months=None,
        expires_at=None,
        status="none",
    )


def create_pending_subscription(
    db: Session,
    user: User,
    *,
    months: int,
    include_ai: bool,
    include_ats: bool,
    quote: PlanQuote | None = None,
) -> tuple[Subscription, PlanQuote]:
    """Replace any existing open order with a new quote.

    Pass ``quote`` for upgrades (supports months=0 add-on-only orders).
    """
    if quote is None:
        quote = quote_plan(months, include_ai=include_ai, include_ats=include_ats)
    now = datetime.now(timezone.utc)

    for old in (
        db.query(Subscription)
        .filter(
            Subscription.user_id == user.id,
            Subscription.status.in_(("pending", "awaiting_confirm")),
        )
        .all()
    ):
        old.status = "cancelled"
        old.updated_at = now

    sub = Subscription(
        user_id=user.id,
        months=int(quote.months),
        include_ai=quote.include_ai,
        include_ats=quote.include_ats,
        base_price=quote.base_price,
        ai_price=quote.ai_price,
        ats_price=quote.ats_price,
        total_price=quote.total,
        currency=quote.currency,
        payment_method="card_to_card",
        status="pending",
        created_at=now,
        updated_at=now,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub, quote


def attach_receipt(
    db: Session,
    subscription_id: int,
    *,
    receipt_file_id: str,
) -> Subscription:
    sub = db.get(Subscription, subscription_id)
    if sub is None:
        raise ValueError("Subscription not found")
    if sub.status not in ("pending", "awaiting_confirm"):
        raise ValueError(f"Cannot attach receipt to status={sub.status}")
    now = datetime.now(timezone.utc)
    sub.receipt_file_id = (receipt_file_id or "")[:256]
    sub.receipt_received_at = now
    sub.status = "awaiting_confirm"
    sub.updated_at = now
    db.commit()
    db.refresh(sub)
    return sub


def activate_subscription(
    db: Session,
    subscription_id: int,
    *,
    activated_by: str = "admin",
) -> Subscription:
    sub = db.get(Subscription, subscription_id)
    if sub is None:
        raise ValueError("Subscription not found")
    if sub.status not in ("pending", "awaiting_confirm", "expired", "cancelled"):
        if sub.status == "active":
            return sub
        raise ValueError(f"Cannot activate status={sub.status}")

    now = datetime.now(timezone.utc)
    existing = get_active_subscription(db, sub.user_id)
    months = int(sub.months or 0)

    # Add-on-only upgrade: merge AI/ATS onto current period (no extra months)
    if months == 0:
        if existing is None or existing.id == sub.id:
            raise ValueError("برای افزونه فقط باید اشتراک فعال داشته باشید")
        sub.include_ai = bool(existing.include_ai or sub.include_ai)
        sub.include_ats = bool(existing.include_ats or sub.include_ats)
        sub.months = int(existing.months)
        sub.expires_at = existing.expires_at
        sub.started_at = existing.started_at or now
        existing.status = "cancelled"
        existing.updated_at = now
        sub.status = "active"
        sub.activated_by = (activated_by or "admin")[:64]
        sub.updated_at = now
        db.commit()
        db.refresh(sub)
        return sub

    # Stack from current expiry if still active; otherwise from now
    start = now
    keep_ai = bool(sub.include_ai)
    keep_ats = bool(sub.include_ats)
    if existing and existing.id != sub.id:
        keep_ai = keep_ai or bool(existing.include_ai)
        keep_ats = keep_ats or bool(existing.include_ats)
        existing.status = "cancelled"
        existing.updated_at = now
        if existing.expires_at:
            exp = existing.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp > now:
                start = exp

    sub.include_ai = keep_ai
    sub.include_ats = keep_ats
    sub.status = "active"
    sub.started_at = now
    sub.expires_at = start + timedelta(days=30 * months)
    sub.activated_by = (activated_by or "admin")[:64]
    sub.updated_at = now
    db.commit()
    db.refresh(sub)
    return sub


def reject_subscription(db: Session, subscription_id: int) -> Subscription:
    sub = db.get(Subscription, subscription_id)
    if sub is None:
        raise ValueError("Subscription not found")
    sub.status = "cancelled"
    sub.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(sub)
    return sub
