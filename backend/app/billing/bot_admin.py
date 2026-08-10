"""Admin Telegram UI — edit plan prices, card details, and AI connectivity (Farsi)."""

from __future__ import annotations

import html
import logging
from typing import Any

from app.billing.commerce import (
    KEY_AI,
    KEY_ATS,
    KEY_BANK_NAME,
    KEY_CARD_HOLDER,
    KEY_CARD_NUMBER,
    KEY_CURRENCY,
    KEY_EXTRA_NOTE,
    KEY_PRICE_1,
    KEY_PRICE_3,
    KEY_PRICE_6,
    KEY_PRICE_12,
    load_commerce,
    save_commerce_field,
)
from app.billing.plans import format_money
from app.config import settings
from app.database import SessionLocal
from app.telegram import keyboards as kb

logger = logging.getLogger(__name__)

PROVIDERS = ("groq", "gemini", "deepseek", "openai", "anthropic")

# Provider role code -> (settings attr, persist key, Farsi label)
AI_ROLES: dict[str, tuple[str, str, str]] = {
    "def": ("ai_provider", "ai_provider", "ارائه‌دهنده پیش‌فرض"),
    "scr": ("ai_screening_provider", "ai_screening_provider", "غربالگری"),
    "prop": ("ai_proposal_provider", "ai_proposal_provider", "پیشنهاد/نوشتن"),
}

# chat_id -> pending field edit
_pending: dict[str, dict[str, str]] = {}

# callback field code -> (db key, label, kind)
FIELDS: dict[str, tuple[str, str, str]] = {
    "p1": (KEY_PRICE_1, "قیمت پلن ۱ ماهه", "float"),
    "p3": (KEY_PRICE_3, "قیمت پلن ۳ ماهه", "float"),
    "p6": (KEY_PRICE_6, "قیمت پلن ۶ ماهه", "float"),
    "p12": (KEY_PRICE_12, "قیمت پلن ۱۲ ماهه", "float"),
    "pai": (KEY_AI, "قیمت ماهانه افزونه هوش مصنوعی", "float"),
    "pats": (KEY_ATS, "قیمت ماهانه افزونه ATS", "float"),
    "cur": (KEY_CURRENCY, "واحد پول (مثلاً IRR)", "text"),
    "card": (KEY_CARD_NUMBER, "شماره کارت", "text"),
    "name": (KEY_CARD_HOLDER, "نام صاحب کارت", "text"),
    "bank": (KEY_BANK_NAME, "نام بانک", "text"),
    "note": (KEY_EXTRA_NOTE, "یادداشت پرداخت (اختیاری)", "text"),
}


def pending_for(chat_id: int | str) -> dict[str, str] | None:
    return _pending.get(str(chat_id))


def clear_pending(chat_id: int | str) -> None:
    _pending.pop(str(chat_id), None)


def set_pending(chat_id: int | str, field_code: str) -> str:
    meta = FIELDS.get(field_code)
    if not meta:
        raise ValueError("فیلد نامشخص")
    _, label, kind = meta
    _pending[str(chat_id)] = {"field": field_code, "label": label, "kind": kind}
    return label


def _esc(v: Any) -> str:
    return html.escape(str(v if v is not None else "—"))


def _api_key_for_provider(provider: str) -> str:
    p = (provider or "").lower().strip()
    if p == "groq":
        return settings.groq_api_key
    if p == "gemini":
        return settings.gemini_api_key
    if p == "deepseek":
        return settings.deepseek_api_key
    if p == "openai":
        return settings.openai_api_key
    if p == "anthropic":
        return settings.anthropic_api_key
    return ""


def _ai_key_status_lines() -> str:
    providers = [
        ("پیش‌فرض", settings.ai_provider),
        ("غربالگری", settings.screening_provider),
        ("پیشنهاد/نوشتن", settings.proposal_provider),
    ]
    lines = ["<b>🤖 وضعیت کلید AI (از .env)</b>"]
    seen: set[str] = set()
    for label, provider in providers:
        p = (provider or "").lower().strip() or "—"
        if p in seen and label != "پیش‌فرض":
            # still show if different role uses same provider once
            pass
        seen.add(p)
        key = _api_key_for_provider(p)
        icon = "✅" if key.strip() else "❌"
        lines.append(
            f"{icon} {label}: <b>{_esc(p)}</b> — کلید {'ست شده' if key.strip() else 'نیست'}"
        )
    lines.append("<i>برای تست زنده، دکمه «بررسی اتصال AI» را بزنید.</i>")
    return "\n".join(lines)


async def _live_ai_test() -> str:
    """Ping configured screening + proposal providers with a tiny prompt."""
    from app.ai.evaluator import (
        _call_anthropic,
        _call_openai_compatible,
        _resolve_provider_call,
    )

    lines = ["<b>🔌 نتیجه تست زنده AI</b>", ""]
    checks = [
        ("غربالگری", settings.screening_provider, settings.screening_model()),
        ("پیشنهاد/نوشتن", settings.proposal_provider, settings.proposal_model()),
    ]
    overall_ok = True
    for label, provider, model in checks:
        p = (provider or "").lower().strip()
        key_ok = bool(_api_key_for_provider(p).strip())
        if not key_ok:
            lines.append(f"❌ <b>{_esc(label)}</b> ({_esc(p)}) — کلید در .env نیست")
            overall_ok = False
            continue
        try:
            system = "You are a connectivity probe. Reply with exactly: OK"
            user = "ping"
            if p == "anthropic":
                reply = _call_anthropic(system, user, model=model, max_tokens=16)
            else:
                api_key, base_url = _resolve_provider_call(p)
                reply = _call_openai_compatible(
                    system,
                    user,
                    api_key=api_key,
                    model=model,
                    provider=p,
                    base_url=base_url,
                    max_tokens=16,
                    json_mode=False,
                )
            snippet = (reply or "").strip().replace("\n", " ")[:80]
            lines.append(
                f"✅ <b>{_esc(label)}</b> ({_esc(p)} / {_esc(model)}) — متصل"
                + (f" · پاسخ: <code>{_esc(snippet)}</code>" if snippet else "")
            )
        except Exception as exc:
            overall_ok = False
            err = html.escape(str(exc)[:220])
            lines.append(
                f"❌ <b>{_esc(label)}</b> ({_esc(p)} / {_esc(model)}) — خطا: {err}"
            )

    lines.append("")
    lines.append("✅ همه چیز وصل است." if overall_ok else "⚠️ یک یا چند اتصال مشکل دارد.")
    return "\n".join(lines)


def _render_provider_pick(role: str) -> tuple[str, dict]:
    meta = AI_ROLES.get(role)
    if not meta:
        raise ValueError("Unknown AI role")
    _, _, label = meta
    text = f"<b>انتخاب {_esc(label)}</b>\n\nیکی از ارائه‌دهنده‌ها را بزنید:"
    rows: list[list[dict]] = []
    row: list[dict] = []
    for p in PROVIDERS:
        key_ok = "✅" if _api_key_for_provider(p).strip() else "❌"
        row.append(kb._btn(f"{key_ok} {p}", f"adm:aiset:{role}:{p}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([kb._btn("« بازگشت", "adm:home")])
    return text, kb._markup(rows)


def _set_ai_provider(role: str, provider: str) -> None:
    provider = provider.lower().strip()
    if provider not in PROVIDERS:
        raise ValueError("ارائه‌دهنده نامعتبر")
    meta = AI_ROLES.get(role)
    if not meta:
        raise ValueError("نقش AI نامعتبر")
    attr, persist_key, _label = meta
    from app.services.settings_service import persist_setting

    db = SessionLocal()
    try:
        setattr(settings, attr, provider)
        persist_setting(db, persist_key, provider)
        # Default also drives screening/proposal when those are empty
        if role == "def":
            if not (settings.ai_screening_provider or "").strip():
                settings.ai_screening_provider = provider
                persist_setting(db, "ai_screening_provider", provider)
            if not (settings.ai_proposal_provider or "").strip():
                settings.ai_proposal_provider = provider
                persist_setting(db, "ai_proposal_provider", provider)
    finally:
        db.close()


def render_admin_home(*, telegram_user_id: int | None = None) -> tuple[str, dict]:
    c = load_commerce()
    uid_line = (
        f"شناسه تلگرام شما: <code>{telegram_user_id}</code>\n"
        if telegram_user_id is not None
        else ""
    )
    text = (
        "<b>🛠 مدیریت فروش (ادمین)</b>\n\n"
        f"{uid_line}"
        f"{_ai_key_status_lines()}\n\n"
        f"واحد پول: <b>{_esc(c.currency)}</b>\n\n"
        f"۱ ماهه: <b>{format_money(c.price_1_month, c.currency)}</b>\n"
        f"۳ ماهه: <b>{format_money(c.price_3_month, c.currency)}</b>\n"
        f"۶ ماهه: <b>{format_money(c.price_6_month, c.currency)}</b>\n"
        f"۱۲ ماهه: <b>{format_money(c.price_12_month, c.currency)}</b>\n"
        f"AI / ماه: <b>{format_money(c.ai_addon_per_month, c.currency)}</b>\n"
        f"ATS / ماه: <b>{format_money(c.ats_addon_per_month, c.currency)}</b>\n\n"
        f"شماره کارت: <code>{_esc(c.card_number or '—')}</code>\n"
        f"نام کارت: <b>{_esc(c.card_holder or '—')}</b>\n"
        f"بانک: <b>{_esc(c.bank_name or '—')}</b>\n"
        f"یادداشت: {_esc(c.extra_note or '—')}\n\n"
        "برای ویرایش یک مورد را انتخاب کنید:"
    )
    rows = [
        [kb._btn("🔌 بررسی اتصال AI", "adm:aitest")],
        [
            kb._btn(f"پیش‌فرض: {settings.ai_provider}", "adm:aipick:def"),
        ],
        [
            kb._btn(f"غربالگری: {settings.screening_provider}", "adm:aipick:scr"),
            kb._btn(f"نوشتن: {settings.proposal_provider}", "adm:aipick:prop"),
        ],
        [
            kb._btn("۱ ماهه", "adm:e:p1"),
            kb._btn("۳ ماهه", "adm:e:p3"),
        ],
        [
            kb._btn("۶ ماهه", "adm:e:p6"),
            kb._btn("۱۲ ماهه", "adm:e:p12"),
        ],
        [
            kb._btn("قیمت AI", "adm:e:pai"),
            kb._btn("قیمت ATS", "adm:e:pats"),
        ],
        [kb._btn("واحد پول", "adm:e:cur")],
        [kb._btn("💳 شماره کارت", "adm:e:card")],
        [kb._btn("👤 نام صاحب کارت", "adm:e:name")],
        [kb._btn("🏦 نام بانک", "adm:e:bank")],
        [kb._btn("📝 یادداشت پرداخت", "adm:e:note")],
        [kb._btn("🔄 تازه‌سازی", "adm:home"), kb._btn("« بستن", "adm:x")],
    ]
    return text, kb._markup(rows)


async def handle_callback(data: str, *, chat_id: int | str, is_admin: bool) -> dict:
    if not is_admin:
        return {"toast": "فقط ادمین", "alert": True}

    parts = data.split(":")
    if len(parts) < 2:
        return {"toast": "نامشخص"}

    op = parts[1]

    if op == "x":
        clear_pending(chat_id)
        return {
            "toast": "بسته شد",
            "edit_text": "پنل ادمین بسته شد.",
            "reply_markup": kb.cleared_keyboard(),
        }

    if op == "home":
        clear_pending(chat_id)
        text, markup = render_admin_home()
        return {"toast": "مدیریت فروش", "edit_text": text, "reply_markup": markup}

    if op == "aitest":
        try:
            report = await _live_ai_test()
        except Exception as exc:
            logger.exception("AI connectivity test failed")
            report = f"❌ تست AI ناموفق بود: {html.escape(str(exc)[:300])}"
        _, markup = render_admin_home()
        return {
            "toast": "تست AI انجام شد",
            "edit_text": report,
            "reply_markup": markup,
        }

    if op == "aipick" and len(parts) >= 3:
        role = parts[2]
        if role not in AI_ROLES:
            return {"toast": "نقش نامعتبر", "alert": True}
        text, markup = _render_provider_pick(role)
        return {"toast": "انتخاب ارائه‌دهنده", "edit_text": text, "reply_markup": markup}

    if op == "aiset" and len(parts) >= 4:
        role, provider = parts[2], parts[3]
        try:
            _set_ai_provider(role, provider)
        except Exception as exc:
            return {"toast": f"خطا: {exc}"[:180], "alert": True}
        text, markup = render_admin_home()
        label = AI_ROLES[role][2] if role in AI_ROLES else role
        return {
            "toast": f"{label} → {provider}",
            "edit_text": text,
            "reply_markup": markup,
        }

    if op == "e" and len(parts) >= 3:
        field = parts[2]
        meta = FIELDS.get(field)
        if not meta:
            return {"toast": "فیلد نامشخص", "alert": True}
        label = set_pending(chat_id, field)
        kind = meta[2]
        hint = (
            "یک عدد بفرستید (مثلاً 990000)."
            if kind == "float"
            else "متن جدید را بفرستید."
        )
        return {
            "toast": "منتظر مقدار…",
            "prompt": (
                f"✏️ <b>{html.escape(label)}</b>\n\n"
                f"{hint}\n"
                "برای انصراف: <code>لغو</code>"
            ),
        }

    return {"toast": "نامشخص"}


async def handle_text_value(chat_id: int | str, text: str) -> dict:
    pending = pending_for(chat_id)
    if not pending:
        return {"handled": False}

    raw = (text or "").strip()
    if raw.lower() in ("cancel", "/cancel", "لغو", "انصراف"):
        clear_pending(chat_id)
        home, markup = render_admin_home()
        return {
            "handled": True,
            "message": "ویرایش لغو شد.",
            "follow_up": home,
            "reply_markup": markup,
        }

    field = pending["field"]
    meta = FIELDS.get(field)
    if not meta:
        clear_pending(chat_id)
        return {"handled": True, "message": "فیلد نامعتبر."}

    db_key, label, kind = meta
    db = SessionLocal()
    try:
        value = raw
        if kind == "float":
            value = str(float(raw.replace(",", "").replace("،", "")))
        save_commerce_field(db, db_key, value)
        clear_pending(chat_id)
        home, markup = render_admin_home()
        return {
            "handled": True,
            "message": f"✅ <b>{html.escape(label)}</b> ذخیره شد.",
            "follow_up": home,
            "reply_markup": markup,
        }
    except Exception as exc:
        logger.exception("Admin commerce edit failed")
        return {
            "handled": True,
            "message": f"❌ ذخیره نشد: {html.escape(str(exc)[:200])}",
        }
    finally:
        db.close()
