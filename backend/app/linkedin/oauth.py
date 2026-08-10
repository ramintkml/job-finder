"""OAuth state management for LinkedIn connect flow."""

from __future__ import annotations

import secrets
import time

_STATE_TTL_SECONDS = 600
_states: dict[str, float] = {}


def create_state() -> str:
    _prune_expired()
    state = secrets.token_urlsafe(24)
    _states[state] = time.time() + _STATE_TTL_SECONDS
    return state


def validate_state(state: str | None) -> bool:
    if not state:
        return False
    _prune_expired()
    expiry = _states.pop(state, None)
    return expiry is not None and expiry >= time.time()


def _prune_expired() -> None:
    now = time.time()
    expired = [key for key, expiry in _states.items() if expiry < now]
    for key in expired:
        _states.pop(key, None)
