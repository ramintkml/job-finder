"""Apply LinkedIn OIDC profile data to LinkedIn job settings."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.linkedin import token_store as li_token_store
from app.linkedin.settings import LinkedInSettings, load_linkedin_settings, save_linkedin_settings


def _name_from_userinfo(userinfo: dict) -> str:
    name = (userinfo.get("name") or "").strip()
    if name:
        return name
    given = (userinfo.get("given_name") or "").strip()
    family = (userinfo.get("family_name") or "").strip()
    return f"{given} {family}".strip()


def apply_linkedin_identity(db: Session, cfg: LinkedInSettings) -> LinkedInSettings:
    """When LinkedIn is connected, name and email always come from the linked account."""
    if not li_token_store.is_connected(db):
        return cfg

    tokens = li_token_store.load_tokens(db)
    name = (tokens.get("linkedin_name") or "").strip()
    email = (tokens.get("linkedin_email") or "").strip()
    if name:
        cfg.applicant_name = name
        cfg.from_name = name
    if email:
        cfg.linkedin_email = email
    return cfg


def apply_userinfo_to_settings(cfg: LinkedInSettings, userinfo: dict) -> LinkedInSettings:
    name = _name_from_userinfo(userinfo)
    email = (userinfo.get("email") or "").strip()

    if name:
        cfg.applicant_name = name
        cfg.from_name = name
    if email:
        cfg.linkedin_email = email

    return cfg


def sync_profile_to_settings(db: Session, userinfo: dict) -> LinkedInSettings:
    cfg = load_linkedin_settings(db)
    cfg = apply_userinfo_to_settings(cfg, userinfo)
    save_linkedin_settings(db, cfg)
    return apply_linkedin_identity(db, cfg)
