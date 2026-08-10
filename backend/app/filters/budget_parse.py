"""Parse budget, currency, and hourly/fixed amounts from project text or API data."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.filters.default_block_phrases import ALLOWED_CURRENCIES

_CURRENCY_CODE = re.compile(
    r"\b(USD|EUR|GBP|CAD|AUD|HKD|INR|PHP|BRL|SGD|NZD|CHF|JPY|CNY|RUB)\b",
    re.IGNORECASE,
)
_AMOUNT = r"[\d,]+(?:\.\d+)?"
_RANGE = re.compile(
    rf"(?:fixed|hourly)\s*:\s*\$?\s*({_AMOUNT})\s*(?:-|to)\s*\$?\s*({_AMOUNT})",
    re.IGNORECASE,
)
_SINGLE = re.compile(
    rf"(?:fixed|hourly)\s*:\s*\$?\s*({_AMOUNT})",
    re.IGNORECASE,
)
_BUDGET_LINE = re.compile(
    rf"budget\s*:\s*\$?\s*({_AMOUNT})(?:\s*(?:-|–|to)\s*\$?\s*({_AMOUNT}))?",
    re.IGNORECASE,
)
# Bare ranges like "$250-$750" or "250 - 750 USD" (common in bot messages)
_BARE_RANGE = re.compile(
    rf"\$?\s*({_AMOUNT})\s*(?:-|–|to)\s*\$?\s*({_AMOUNT})(?:\s*(?:USD|EUR|GBP|CAD|AUD))?",
    re.IGNORECASE,
)


@dataclass
class ParsedBudget:
    currency: str | None = None
    is_hourly: bool = False
    min_amount: float | None = None
    max_amount: float | None = None

    @property
    def hourly_floor(self) -> float | None:
        if not self.is_hourly:
            return None
        if self.min_amount is not None:
            return self.min_amount
        return self.max_amount

    @property
    def fixed_ceiling(self) -> float | None:
        if self.is_hourly:
            return None
        if self.max_amount is not None:
            return self.max_amount
        return self.min_amount


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _detect_currency(text: str) -> str | None:
    for match in _CURRENCY_CODE.finditer(text):
        return match.group(1).upper()
    if "€" in text:
        return "EUR"
    if "£" in text:
        return "GBP"
    if "A$" in text or "AUD" in text.upper():
        return "AUD"
    if "C$" in text or "CAD" in text.upper():
        return "CAD"
    if "HK$" in text or "HKD" in text.upper():
        return "HKD"
    if "$" in text or "USD" in text.upper():
        return "USD"
    return None


def _detect_hourly(text: str) -> bool:
    lower = text.lower()
    if re.search(r"\bhourly\b", lower):
        return True
    if re.search(r"\bfixed\b", lower):
        return False
    return "per hour" in lower or "/hr" in lower


def parse_budget_from_text(text: str) -> ParsedBudget:
    parsed = ParsedBudget(
        currency=_detect_currency(text),
        is_hourly=_detect_hourly(text),
    )
    range_match = _RANGE.search(text)
    if range_match:
        parsed.min_amount = _to_float(range_match.group(1))
        parsed.max_amount = _to_float(range_match.group(2))
        return parsed

    budget_match = _BUDGET_LINE.search(text)
    if budget_match:
        parsed.min_amount = _to_float(budget_match.group(1))
        parsed.max_amount = _to_float(budget_match.group(2)) or parsed.min_amount
        if "hourly" in text.lower():
            parsed.is_hourly = True
        elif "fixed" in text.lower():
            parsed.is_hourly = False
        return parsed

    single_match = _SINGLE.search(text)
    if single_match:
        amount = _to_float(single_match.group(1))
        parsed.min_amount = amount
        parsed.max_amount = amount
        return parsed

    bare_match = _BARE_RANGE.search(text)
    if bare_match:
        parsed.min_amount = _to_float(bare_match.group(1))
        parsed.max_amount = _to_float(bare_match.group(2))
    return parsed


def parse_budget_from_api(project: dict[str, Any]) -> ParsedBudget:
    ptype = str(project.get("type") or project.get("project_type") or "").lower()
    is_hourly = "hourly" in ptype

    budget = project.get("budget") or {}
    if not isinstance(budget, dict):
        budget = {}

    currency = None
    cur = project.get("currency") or budget.get("currency")
    if isinstance(cur, dict):
        currency = (cur.get("code") or cur.get("sign") or "").upper() or None
    elif isinstance(cur, str):
        currency = cur.upper()

    minimum = _to_float(budget.get("minimum"))
    maximum = _to_float(budget.get("maximum"))
    average = _to_float(budget.get("average"))
    amount = _to_float(budget.get("amount"))

    if minimum is None and maximum is None:
        if average is not None:
            minimum = maximum = average
        elif amount is not None:
            minimum = maximum = amount

    title = str(project.get("title") or "")
    description = str(project.get("description") or project.get("preview_description") or "")
    text_fallback = parse_budget_from_text(f"{title}\n{description}\n{ptype}")

    if currency is None:
        currency = text_fallback.currency

    return ParsedBudget(
        currency=currency,
        is_hourly=is_hourly or text_fallback.is_hourly,
        min_amount=minimum if minimum is not None else text_fallback.min_amount,
        max_amount=maximum if maximum is not None else text_fallback.max_amount,
    )


def currency_allowed(currency: str | None) -> bool:
    if not currency:
        return False
    return currency.upper() in ALLOWED_CURRENCIES


def compute_bid_amount(parsed: ParsedBudget, discount: float = 0.15) -> float | None:
    """Bid at (1 - discount) of the budget range average, or of a single amount."""
    low = parsed.min_amount
    high = parsed.max_amount
    if low is not None and high is not None:
        average = (low + high) / 2
    elif high is not None:
        average = high
    elif low is not None:
        average = low
    else:
        return None
    amount = average * (1 - discount)
    if amount.is_integer():
        return float(int(amount))
    return round(amount, 2)
