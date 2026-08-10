"""Sellable plan catalog: duration tiers + optional AI / ATS add-ons."""

from __future__ import annotations

from dataclasses import dataclass

from app.billing.commerce import load_commerce
from app.config import settings

# Supported subscription lengths (months)
PLAN_MONTHS: tuple[int, ...] = (1, 3, 6, 12)

# Duration discount on AI / ATS add-ons (each addon priced separately)
ADDON_DISCOUNT_PCT: dict[int, float] = {
    1: 0.0,
    3: 3.0,
    6: 5.0,
    12: 10.0,
}


@dataclass(frozen=True)
class PlanQuote:
    months: int
    include_ai: bool
    include_ats: bool
    base_price: float
    ai_price: float
    ats_price: float
    total: float
    currency: str
    discount_pct: float = 0.0
    ai_before_discount: float = 0.0
    ats_before_discount: float = 0.0
    ai_discount: float = 0.0
    ats_discount: float = 0.0

    @property
    def label(self) -> str:
        parts = [f"{self.months}-month"]
        if self.include_ai:
            parts.append("AI")
        if self.include_ats:
            parts.append("ATS")
        return " + ".join(parts)

    @property
    def addon_discount_total(self) -> float:
        return float(int(round(self.ai_discount + self.ats_discount)))

    @property
    def has_addon_discount(self) -> bool:
        return self.discount_pct > 0 and self.addon_discount_total > 0


def addon_discount_percent(months: int) -> float:
    """Percent off each AI/ATS line for the given duration."""
    return float(ADDON_DISCOUNT_PCT.get(int(months), 0.0))


def _money_round(value: float) -> float:
    return float(int(round(float(value or 0))))


def _apply_addon_discount(gross: float, months: int) -> tuple[float, float, float]:
    """Return (net, gross, discount_amount) for one addon line."""
    pct = addon_discount_percent(months)
    gross = _money_round(float(gross))
    if gross <= 0 or pct <= 0:
        return gross, gross, 0.0
    discount = _money_round(gross * (pct / 100.0))
    net = _money_round(gross - discount)
    return net, gross, discount


def _base_price(months: int) -> float:
    c = load_commerce()
    prices = {
        1: c.price_1_month,
        3: c.price_3_month,
        6: c.price_6_month,
        12: c.price_12_month,
    }
    if months not in prices:
        raise ValueError(f"Unsupported plan length: {months}")
    return float(prices[months])


def quote_plan(
    months: int,
    *,
    include_ai: bool = False,
    include_ats: bool = False,
) -> PlanQuote:
    """Price a subscription: base duration + optional AI/ATS (with duration discount)."""
    months = int(months)
    if months not in PLAN_MONTHS:
        raise ValueError(f"Plan must be one of {PLAN_MONTHS}")

    c = load_commerce()
    base = _base_price(months)
    pct = addon_discount_percent(months)

    ai_gross = float(c.ai_addon_per_month) * months if include_ai else 0.0
    ats_gross = float(c.ats_addon_per_month) * months if include_ats else 0.0
    ai_net, ai_gross, ai_disc = _apply_addon_discount(ai_gross, months)
    ats_net, ats_gross, ats_disc = _apply_addon_discount(ats_gross, months)

    total = _money_round(base + ai_net + ats_net)
    return PlanQuote(
        months=months,
        include_ai=include_ai,
        include_ats=include_ats,
        base_price=_money_round(base),
        ai_price=ai_net,
        ats_price=ats_net,
        total=total,
        currency=(c.currency or "USD").strip().upper() or "USD",
        discount_pct=pct,
        ai_before_discount=ai_gross,
        ats_before_discount=ats_gross,
        ai_discount=ai_disc,
        ats_discount=ats_disc,
    )


def quote_upgrade(
    extra_months: int,
    *,
    want_ai: bool,
    want_ats: bool,
    current_ai: bool,
    current_ats: bool,
    days_left: int,
) -> PlanQuote:
    """Price an upgrade: extend months and/or add AI/ATS for remaining time.

    Duration discount applies to AI/ATS charged for ``extra_months`` (1/3/6/12).
    Pro-rated remaining-day add-ons are not discounted (fractional month).
    """
    extra_months = int(extra_months)
    if extra_months not in (0, *PLAN_MONTHS):
        raise ValueError(f"Extension must be 0 or one of {PLAN_MONTHS}")

    want_ai = bool(want_ai or current_ai)
    want_ats = bool(want_ats or current_ats)

    c = load_commerce()
    base = _base_price(extra_months) if extra_months in PLAN_MONTHS else 0.0
    rem_frac = max(0.0, float(days_left)) / 30.0
    pct = addon_discount_percent(extra_months) if extra_months in PLAN_MONTHS else 0.0

    ai_gross = 0.0
    ats_gross = 0.0
    if want_ai:
        if extra_months > 0:
            ai_gross += float(c.ai_addon_per_month) * extra_months
        if not current_ai and rem_frac > 0:
            # remaining-day portion stays at list price (no multi-month discount)
            pass  # added after discount on extension portion
    if want_ats:
        if extra_months > 0:
            ats_gross += float(c.ats_addon_per_month) * extra_months

    ai_net, ai_gross_ext, ai_disc = _apply_addon_discount(ai_gross, extra_months if extra_months else 1)
    ats_net, ats_gross_ext, ats_disc = _apply_addon_discount(ats_gross, extra_months if extra_months else 1)

    # Pro-rate newly added addons for remaining days (no duration discount)
    if want_ai and not current_ai and rem_frac > 0:
        ai_net = _money_round(ai_net + float(c.ai_addon_per_month) * rem_frac)
        ai_gross_ext = _money_round(ai_gross_ext + float(c.ai_addon_per_month) * rem_frac)
    if want_ats and not current_ats and rem_frac > 0:
        ats_net = _money_round(ats_net + float(c.ats_addon_per_month) * rem_frac)
        ats_gross_ext = _money_round(ats_gross_ext + float(c.ats_addon_per_month) * rem_frac)

    total = _money_round(base + ai_net + ats_net)
    if total <= 0:
        raise ValueError("هیچ تغییری برای ارتقا انتخاب نشده")

    return PlanQuote(
        months=extra_months,
        include_ai=want_ai,
        include_ats=want_ats,
        base_price=_money_round(base),
        ai_price=ai_net,
        ats_price=ats_net,
        total=total,
        currency=(c.currency or "USD").strip().upper() or "USD",
        discount_pct=pct,
        ai_before_discount=ai_gross_ext,
        ats_before_discount=ats_gross_ext,
        ai_discount=ai_disc,
        ats_discount=ats_disc,
    )


def format_money(amount: float, currency: str | None = None) -> str:
    """Accounting-style whole numbers, e.g. ``IRR 1,250,000`` (no decimals)."""
    if currency:
        cur = currency.strip().upper()
    else:
        cur = (load_commerce().currency or settings.plan_currency or "USD").strip().upper()
    n = int(round(float(amount or 0)))
    if n < 0:
        return f"{cur} ({abs(n):,})"
    return f"{cur} {n:,}"


def format_addon_discount_note(quote: PlanQuote) -> str:
    """Farsi lines explaining AI/ATS duration discount (empty if none)."""
    if quote.months <= 1 or quote.discount_pct <= 0:
        return ""
    if not quote.include_ai and not quote.include_ats:
        return (
            f"💡 برای پلن‌های چندماهه، روی افزونه‌های هوش مصنوعی و ATS "
            f"<b>{quote.discount_pct:g}٪ تخفیف</b> اعمال می‌شود "
            f"(اگر افزونه را روشن کنید)."
        )

    lines = [
        f"🎁 <b>تخفیف مدت {_month_fa(quote.months)}:</b> "
        f"<b>{quote.discount_pct:g}٪</b> روی هر افزونه"
    ]
    if quote.include_ai and quote.ai_discount > 0:
        lines.append(
            f"• هوش مصنوعی: {format_money(quote.ai_before_discount, quote.currency)} "
            f"← <b>{format_money(quote.ai_price, quote.currency)}</b> "
            f"(−{format_money(quote.ai_discount, quote.currency)})"
        )
    if quote.include_ats and quote.ats_discount > 0:
        lines.append(
            f"• ATS: {format_money(quote.ats_before_discount, quote.currency)} "
            f"← <b>{format_money(quote.ats_price, quote.currency)}</b> "
            f"(−{format_money(quote.ats_discount, quote.currency)})"
        )
    if quote.addon_discount_total > 0:
        lines.append(
            f"جمع تخفیف افزونه‌ها: <b>−{format_money(quote.addon_discount_total, quote.currency)}</b>"
        )
    return "\n".join(lines)


def _month_fa(months: int) -> str:
    return {1: "۱ ماهه", 3: "۳ ماهه", 6: "۶ ماهه", 12: "۱۲ ماهه"}.get(
        int(months), f"{months} ماهه"
    )
