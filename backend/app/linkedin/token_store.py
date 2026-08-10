"""Persist LinkedIn OAuth tokens and profile snapshot in app_settings."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.database import AppSettings

_KEYS = (
    "linkedin_access_token",
    "linkedin_refresh_token",
    "linkedin_member_id",
    "linkedin_name",
    "linkedin_email",
    "linkedin_picture",
    "linkedin_connected_at",
)


def _get(db: Session, key: str) -> str:
    row = db.get(AppSettings, key)
    return row.value if row and row.value else ""


def _set(db: Session, key: str, value: str) -> None:
    row = db.get(AppSettings, key)
    if row:
        row.value = value
    else:
        db.add(AppSettings(key=key, value=value))


def is_connected(db: Session) -> bool:
    return bool(_get(db, "linkedin_access_token").strip())


def load_tokens(db: Session) -> dict[str, str]:
    return {key: _get(db, key) for key in _KEYS}


def save_tokens(
    db: Session,
    *,
    access_token: str,
    refresh_token: str = "",
    member_id: str = "",
    name: str = "",
    email: str = "",
    picture: str = "",
) -> None:
    _set(db, "linkedin_access_token", access_token)
    _set(db, "linkedin_refresh_token", refresh_token)
    if member_id:
        _set(db, "linkedin_member_id", member_id)
    if name:
        _set(db, "linkedin_name", name)
    if email:
        _set(db, "linkedin_email", email)
    if picture:
        _set(db, "linkedin_picture", picture)
    _set(db, "linkedin_connected_at", datetime.now(timezone.utc).isoformat())
    db.commit()


def save_profile_snapshot(
    db: Session,
    *,
    member_id: str = "",
    name: str = "",
    email: str = "",
    picture: str = "",
) -> None:
    if member_id:
        _set(db, "linkedin_member_id", member_id)
    if name:
        _set(db, "linkedin_name", name)
    if email:
        _set(db, "linkedin_email", email)
    if picture:
        _set(db, "linkedin_picture", picture)
    db.commit()


def clear_tokens(db: Session) -> None:
    for key in _KEYS:
        row = db.get(AppSettings, key)
        if row:
            row.value = ""
    db.commit()


def status_payload(db: Session, *, client_configured: bool) -> dict:
    tokens = load_tokens(db)
    return {
        "linkedin_connected": is_connected(db),
        "linkedin_client_configured": client_configured,
        "linkedin_member_id": tokens.get("linkedin_member_id") or None,
        "linkedin_name": tokens.get("linkedin_name") or None,
        "linkedin_email": tokens.get("linkedin_email") or None,
        "linkedin_picture": tokens.get("linkedin_picture") or None,
        "linkedin_connected_at": tokens.get("linkedin_connected_at") or None,
        "linkedin_has_refresh_token": bool(tokens.get("linkedin_refresh_token", "").strip()),
    }
