"""Cookie sessions for the dashboard; legacy operator APIs require admin access."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.config import DATA_DIR, settings

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "career_session"
TTL = 12 * 3600


def _signing_key() -> bytes:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / ".session_key"
    try:
        with path.open("xb") as out:
            out.write(secrets.token_bytes(32))
        path.chmod(0o600)
    except FileExistsError:
        pass
    return path.read_bytes()


@dataclass
class Principal:
    telegram_user_id: int
    is_admin: bool = False


def issue_session(user_id: int, *, admin: bool = False) -> str:
    data = f"{int(user_id)}:{int(admin)}:{int(time.time()) + TTL}"
    return data + ":" + hmac.new(_signing_key(), data.encode(), hashlib.sha256).hexdigest()


def current_user(request: Request) -> Principal:
    raw = request.cookies.get(COOKIE, "")
    try:
        uid, admin, expires, signature = raw.split(":")
        data = f"{uid}:{admin}:{expires}"
        expected = hmac.new(_signing_key(), data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected) or int(expires) <= time.time():
            raise ValueError()
        principal = Principal(int(uid), admin == "1")
        if not principal.is_admin:
            from app.database import SessionLocal, User
            with SessionLocal() as db:
                row = db.query(User).filter(User.telegram_user_id == principal.telegram_user_id).first()
                if not row or not row.is_active:
                    raise ValueError()
        return principal
    except (ValueError, TypeError):
        raise HTTPException(401, "Sign in required")


def require_admin(user: Principal = Depends(current_user)) -> Principal:
    if not user.is_admin:
        raise HTTPException(403, "Administrator access required")
    return user


class LoginBody(BaseModel):
    password: str = ""
    init_data: str = ""


# Bounded per-process rate limit; reverse proxy should also rate-limit /auth/login.
_attempts: dict[str, tuple[float, int]] = {}


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response):
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Invalid origin")
    host = request.client.host if request.client else "unknown"
    now = time.time()
    for key, (start, _) in list(_attempts.items()):
        if now - start >= 300:
            _attempts.pop(key, None)
    start, count = _attempts.get(host, (now, 0))
    if count >= 10 or len(_attempts) > 10000:
        raise HTTPException(429, "Please try again later")
    _attempts[host] = (start, count + 1)
    admin = False
    uid = 0
    if body.init_data:
        from app.database import SessionLocal, User
        pairs = parse_qsl(body.init_data, keep_blank_values=True)
        fields = dict(pairs)
        signature = fields.pop("hash", "")
        if len(pairs) != len(dict(pairs)) or not settings.telegram_review_bot_token:
            raise HTTPException(401, "Invalid Telegram login")
        key = hmac.new(b"WebAppData", settings.telegram_review_bot_token.encode(), hashlib.sha256).digest()
        payload = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
        expected = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
        try:
            age = now - int(fields["auth_date"])
            if not hmac.compare_digest(signature, expected) or not 0 <= age <= 300:
                raise ValueError()
            uid = int(json.loads(fields["user"])["id"])
        except (KeyError, ValueError, TypeError, json.JSONDecodeError):
            raise HTTPException(401, "Invalid Telegram login")
        with SessionLocal() as db:
            user = db.query(User).filter(User.telegram_user_id == uid).first()
            if not user or not user.is_active:
                raise HTTPException(403, "Start the Telegram bot first")
        admin = uid in settings.admin_telegram_ids
    else:
        password = settings.dashboard_admin_password
        if not password or not hmac.compare_digest(body.password, password):
            raise HTTPException(401, "Invalid credentials (configure DASHBOARD_ADMIN_PASSWORD)")
        admin = True
    response.set_cookie(COOKIE, issue_session(uid, admin=admin), httponly=True,
                        secure=request.url.scheme == "https", samesite="strict", max_age=TTL)
    _attempts.pop(host, None)
    return {"is_admin": admin, "telegram_user_id": uid}


@router.get("/me")
def me(user: Principal = Depends(current_user)):
    return {"is_admin": user.is_admin, "telegram_user_id": user.telegram_user_id}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}
