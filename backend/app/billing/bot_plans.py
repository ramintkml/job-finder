"""Telegram UI for subscription plans — Farsi (card-to-card)."""

from __future__ import annotations

import html
import logging
from typing import Any

from app.billing.plans import (
    PLAN_MONTHS,
    format_addon_discount_note,
    format_money,
    quote_plan,
    quote_upgrade,
)
from app.billing.service import (
    activate_subscription,
    attach_receipt,
    create_pending_subscription,
    get_active_subscription,
    get_or_create_user,
    get_pending_subscription,
    get_user_by_telegram_id,
    reject_subscription,
    user_entitlements,
)
from app.database import SessionLocal, Subscription
from app.telegram import keyboards as kb

logger = logging.getLogger(__name__)

_drafts: dict[int, dict[str, Any]] = {}
_awaiting_receipt: dict[int, int] = {}

_MONTH_LABEL = {
    1: "۱ ماهه",
    3: "۳ ماهه",
    6: "۶ ماهه",
    12: "۱۲ ماهه",
}


def _month_label(months: int) -> str:
    return _MONTH_LABEL.get(int(months), f"{months} ماهه")


def _draft(telegram_user_id: int) -> dict[str, Any]:
    d = _drafts.get(telegram_user_id)
    if d is None:
        d = {
            "mode": "new",
            "months": 1,
            "include_ai": False,
            "include_ats": False,
            "locked_ai": False,
            "locked_ats": False,
            "days_left": 0,
        }
        _drafts[telegram_user_id] = d
    return d


def _seed_upgrade_draft(telegram_user_id: int, *, include_ai: bool, include_ats: bool, days_left: int) -> dict[str, Any]:
    d = {
        "mode": "upgrade",
        "months": 1,
        "include_ai": bool(include_ai),
        "include_ats": bool(include_ats),
        "locked_ai": bool(include_ai),
        "locked_ats": bool(include_ats),
        "days_left": max(0, int(days_left)),
    }
    _drafts[telegram_user_id] = d
    return d


def _days_left(expires_at) -> int:
    from datetime import datetime, timezone

    if expires_at is None:
        return 0
    exp = expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = exp - now
    return max(0, int(delta.total_seconds() // 86400))


def _status_label(status: str) -> str:
    return {
        "none": "بدون اشتراک",
        "pending": "در انتظار پرداخت",
        "awaiting_confirm": "در انتظار تأیید ادمین",
        "active": "فعال",
        "expired": "منقضی",
        "cancelled": "لغو شده",
    }.get(status, status)


def clear_draft(telegram_user_id: int) -> None:
    _drafts.pop(telegram_user_id, None)


def set_awaiting_receipt(telegram_user_id: int, subscription_id: int) -> None:
    _awaiting_receipt[telegram_user_id] = subscription_id


def clear_awaiting_receipt(telegram_user_id: int) -> None:
    _awaiting_receipt.pop(telegram_user_id, None)


def awaiting_receipt_subscription_id(telegram_user_id: int) -> int | None:
    return _awaiting_receipt.get(telegram_user_id)


def _esc(v: Any) -> str:
    return html.escape(str(v if v is not None else "—"))


def _bool_icon(v: bool) -> str:
    return "✅" if v else "❌"


def _extras_label(*, include_ai: bool, include_ats: bool) -> str:
    extras = []
    if include_ai:
        extras.append("هوش مصنوعی")
    if include_ats:
        extras.append("ATS")
    return (" + " + " + ".join(extras)) if extras else ""


def _card_payment_block(*, amount: float, currency: str, order_id: int) -> str:
    from app.billing.commerce import load_commerce

    c = load_commerce()
    card = (c.card_number or "").strip() or "(شماره کارت در پنل ادمین تنظیم نشده)"
    holder = (c.card_holder or "").strip() or "—"
    bank = (c.bank_name or "").strip()
    note = (c.extra_note or "").strip()

    lines = [
        "<b>💳 پرداخت کارت‌به‌کارت</b>",
        "",
        f"💵 مبلغ: <b>{format_money(amount, currency)}</b>",
        f"💳 شماره کارت: <code>{_esc(card)}</code>",
        f"👤 به نام: <b>{_esc(holder)}</b>",
    ]
    if bank:
        lines.append(f"🏦 بانک: <b>{_esc(bank)}</b>")
    lines.extend(
        [
            f"🧾 شماره سفارش: <code>{order_id}</code>",
            "",
            "۱. مبلغ را <b>دقیقاً</b> به کارت بالا واریز کنید.",
            "۲. <b>عکس رسید</b> (یا تصویر/PDF) را برای همین ربات بفرستید.",
            "۳. بعد از تأیید ادمین، پیام فعال‌سازی برایتان می‌آید.",
        ]
    )
    if note:
        lines.extend(["", _esc(note)])
    return "\n".join(lines)


def render_account_status(*, telegram_user_id: int) -> tuple[str, dict]:
    """User-facing account + subscription + Gmail connection status."""
    from app.linkedin.email_send import gmail_configured
    from app.linkedin.settings import load_linkedin_settings

    db = SessionLocal()
    try:
        user = get_user_by_telegram_id(db, telegram_user_id)
        if user is None:
            text = (
                "<b>📋 حساب من</b>\n\n"
                "هنوز حسابی ندارید.\n"
                "برای ساخت حساب کاربری می‌توانید از دکمه زیر استفاده کنید"
            )
            rows = [
                [kb._btn("ساخت حساب کاربری", "pl:home")],
            ]
            return text, kb._markup(rows)

        ent = user_entitlements(db, user.id)
        active = get_active_subscription(db, user.id)
        pending = get_pending_subscription(db, user.id)
        li_cfg = load_linkedin_settings(db)
        gmail_ok = gmail_configured(li_cfg)
        gmail_addr = (li_cfg.gmail_address or "").strip()
        gmail_pwd_set = bool((li_cfg.gmail_app_password or "").strip())

        uname = f"@{user.username}" if user.username else "—"
        name = user.first_name or "—"
        created = user.created_at.strftime("%Y-%m-%d") if user.created_at else "—"

        if gmail_ok:
            gmail_lines = [
                "📧 <b>جیمیل</b>",
                f"وضعیت: {_bool_icon(True)} متصل",
                f"آدرس: <code>{_esc(gmail_addr)}</code>",
                f"رمز اپ: {_bool_icon(True)} ذخیره شده",
            ]
        else:
            missing = []
            if not gmail_addr:
                missing.append("آدرس")
            if not gmail_pwd_set:
                missing.append("رمز اپ")
            miss = " و ".join(missing) if missing else "ناقص"
            gmail_lines = [
                "📧 <b>جیمیل</b>",
                f"وضعیت: {_bool_icon(False)} متصل نیست",
                f"آدرس: <code>{_esc(gmail_addr or 'تنظیم نشده')}</code>",
                f"رمز اپ: {_bool_icon(gmail_pwd_set)} "
                + ("ذخیره شده" if gmail_pwd_set else "تنظیم نشده"),
                f"کمبود: <b>{_esc(miss)}</b>",
            ]

        lines = [
            "<b>📋 حساب من</b>",
            "",
            "👤 <b>حساب کاربری</b>",
            f"📝 نام: <b>{_esc(name)}</b>",
            f"🔖 یوزرنیم: <b>{_esc(uname)}</b>",
            f"🆔 شناسه تلگرام: <code>{user.telegram_user_id}</code>",
            f"📅 عضویت از: <b>{created}</b>",
            "",
            *gmail_lines,
            "",
            "📦 <b>اشتراک</b>",
            f"📊 وضعیت: <b>{_status_label(ent.status)}</b>",
        ]

        if ent.status == "active" and active:
            days = _days_left(active.expires_at)
            exp = active.expires_at.strftime("%Y-%m-%d") if active.expires_at else "—"
            started = active.started_at.strftime("%Y-%m-%d") if active.started_at else "—"
            lines.extend(
                [
                    f"⏱ پلن: <b>{_month_label(int(active.months))}</b>",
                    f"🤖 هوش مصنوعی: {_bool_icon(bool(active.include_ai))}",
                    f"📊 ATS: {_bool_icon(bool(active.include_ats))}",
                    f"▶️ شروع: <b>{started}</b>",
                    f"🏁 انقضا: <b>{exp}</b>",
                    f"⏳ روز باقی‌مانده: <b>{days}</b>",
                    f"🧾 شماره سفارش فعال: <code>{active.id}</code>",
                    f"💵 مبلغ پرداخت‌شده: <b>{format_money(active.total_price, active.currency)}</b>",
                ]
            )
        else:
            lines.append("پلن فعال ندارید.")
            lines.append(f"🤖 هوش مصنوعی: {_bool_icon(False)}")
            lines.append(f"📊 ATS: {_bool_icon(False)}")

        if pending:
            extra = _extras_label(
                include_ai=bool(pending.include_ai), include_ats=bool(pending.include_ats)
            )
            plan_bit = (
                "افزونه (بدون تمدید)"
                if int(pending.months or 0) == 0
                else _month_label(int(pending.months))
            )
            lines.extend(
                [
                    "",
                    "📤 <b>سفارش باز</b>",
                    f"🧾 #{pending.id} · {plan_bit}{extra}",
                    f"💵 مبلغ: <b>{format_money(pending.total_price, pending.currency)}</b>",
                    f"📊 وضعیت: <b>{_status_label(pending.status)}</b>",
                ]
            )

        rows: list[list[dict]] = [
            [
                kb._btn(
                    "📧 تنظیم جیمیل" if not gmail_ok else "📧 مدیریت جیمیل",
                    "s:c:li",
                ),
                kb._btn("🔌 تست جیمیل", "s:g:test"),
            ],
        ]
        if ent.status == "active":
            rows.append([kb._btn("⬆️ ارتقا", "pl:up"), kb._btn("💎 پلن‌ها", "pl:home")])
        else:
            rows.append([kb._btn("💎 پلن‌ها", "pl:home")])
        return "\n".join(lines), kb._markup(rows)
    finally:
        db.close()


def render_upgrade_builder(telegram_user_id: int) -> tuple[str, dict]:
    d = _draft(telegram_user_id)
    if d.get("mode") != "upgrade":
        return render_account_status(telegram_user_id=telegram_user_id)

    try:
        q = quote_upgrade(
            int(d.get("months") or 0),
            want_ai=bool(d.get("include_ai")),
            want_ats=bool(d.get("include_ats")),
            current_ai=bool(d.get("locked_ai")),
            current_ats=bool(d.get("locked_ats")),
            days_left=int(d.get("days_left") or 0),
        )
        price_ok = True
        price_err = ""
    except ValueError as exc:
        q = None
        price_ok = False
        price_err = str(exc)

    months = int(d.get("months") or 0)
    days = int(d.get("days_left") or 0)
    locked_ai = bool(d.get("locked_ai"))
    locked_ats = bool(d.get("locked_ats"))
    want_ai = bool(d.get("include_ai"))
    want_ats = bool(d.get("include_ats"))

    ext_label = "بدون تمدید (فقط افزونه)" if months == 0 else _month_label(months)
    text_lines = [
        "<b>⬆️ ارتقای پلن</b>",
        "",
        f"⏳ روز باقی‌مانده از اشتراک فعلی: <b>{days}</b>",
        f"🤖 هوش مصنوعی فعلی: {_bool_icon(locked_ai)}",
        f"📊 ATS فعلی: {_bool_icon(locked_ats)}",
        "",
        f"⏱ تمدید: <b>{ext_label}</b>",
        f"🤖 هوش مصنوعی بعد از ارتقا: {_bool_icon(want_ai)}",
        f"📊 ATS بعد از ارتقا: {_bool_icon(want_ats)}",
        "",
    ]
    if price_ok and q is not None:
        discount_note = format_addon_discount_note(q)
        text_lines.extend(
            [
                f"💵 پایه تمدید: <b>{format_money(q.base_price, q.currency)}</b>",
                f"🤖 هوش مصنوعی: <b>{format_money(q.ai_price, q.currency)}</b>",
                f"📊 ATS: <b>{format_money(q.ats_price, q.currency)}</b>",
            ]
        )
        if discount_note:
            text_lines.append("")
            text_lines.append(discount_note)
        text_lines.extend(
            [
                "",
                f"💰 <b>جمع: {format_money(q.total, q.currency)}</b>",
                "",
                "<i>افزونه جدید برای روزهای باقی‌مانده به‌صورت نسبی حساب می‌شود. "
                "مدت تمدید به انتهای اشتراک فعلی اضافه می‌شود.</i>",
            ]
        )
    else:
        text_lines.append(f"⚠️ {_esc(price_err or 'مبلغ قابل محاسبه نیست')}")
        text_lines.append("مدت تمدید یا یک افزونهٔ جدید انتخاب کنید.")

    month_row = [
        kb._btn(f"{'✅' if months == 0 else '○'} بدون تمدید", "pl:m:0"),
    ]
    rows = [
        month_row,
        [
            kb._btn(f"{'✅' if m == months else '○'} {_month_label(m)}", f"pl:m:{m}")
            for m in PLAN_MONTHS[:2]
        ],
        [
            kb._btn(f"{'✅' if m == months else '○'} {_month_label(m)}", f"pl:m:{m}")
            for m in PLAN_MONTHS[2:]
        ],
        [
            kb._btn(
                f"{_bool_icon(want_ai)} هوش مصنوعی"
                + (" (فعال)" if locked_ai else ""),
                "pl:t:ai",
            ),
            kb._btn(
                f"{_bool_icon(want_ats)} ATS" + (" (فعال)" if locked_ats else ""),
                "pl:t:ats",
            ),
        ],
    ]
    if price_ok:
        rows.append([kb._btn("✅ تأیید و پرداخت کارت‌به‌کارت", "pl:buy")])
    rows.append([kb._btn("« وضعیت حساب", "pl:status"), kb._btn("« پلن‌ها", "pl:home")])
    return "\n".join(text_lines), kb._markup(rows)


def render_plans_home(*, telegram_user_id: int | None = None) -> tuple[str, dict]:
    status_line = "اشتراک فعالی ندارید"
    pending_line = ""
    pending_sub_id: int | None = None
    if telegram_user_id is not None:
        db = SessionLocal()
        try:
            user = get_user_by_telegram_id(db, telegram_user_id)
            if user:
                ent = user_entitlements(db, user.id)
                if ent.status == "active" and ent.expires_at:
                    extra = _extras_label(include_ai=ent.include_ai, include_ats=ent.include_ats)
                    exp = ent.expires_at.strftime("%Y-%m-%d")
                    status_line = (
                        f"فعال: <b>{_month_label(ent.months or 0)}</b>{extra} · "
                        f"تا <b>{exp}</b>"
                    )
                else:
                    status_line = "اشتراک فعالی ندارید"
                    pending = get_pending_subscription(db, user.id)
                    if pending:
                        pending_sub_id = pending.id
                        if pending.status == "awaiting_confirm":
                            pending_line = (
                                f"\nرسید سفارش <code>{pending.id}</code> دریافت شد · "
                                f"{format_money(pending.total_price, pending.currency)} "
                                "(در انتظار تأیید ادمین)"
                            )
                        else:
                            pending_line = (
                                f"\nسفارش باز <code>{pending.id}</code> · "
                                f"{format_money(pending.total_price, pending.currency)} "
                                "(کارت‌به‌کارت — رسید را بفرستید)"
                            )
        finally:
            db.close()

    text = (
        "برای ساخت حساب کاربریت می‌تونی از دکمه‌های زیر استفاده کنی.\n\n"
        f"{status_line}{pending_line}\n\n"
        "پلن پایه: جستجوی شغل لینکدین + اعلان در تلگرام.\n"
        "افزونه‌ها:\n"
        "• هوش مصنوعی برای نوشتن و بهبود رزومه\n"
        "• سیستم امتیازدهی ATS برای پیدا کردن مشکلات رزومه\n\n"
        "اگر افزونه‌ها رو روی پلن‌های بیشتر از یک ماه فعال کنی شامل تخفیف هم می‌شن\n"
        "• ۳ ماهه: <b>۳٪</b>\n"
        "• ۶ ماهه: <b>۵٪</b>\n"
        "• ۱۲ ماهه: <b>۱۰٪</b>"
    )
    rows = [
        [kb._btn(_month_label(m), f"pl:m:{m}") for m in PLAN_MONTHS[:2]],
        [kb._btn(_month_label(m), f"pl:m:{m}") for m in PLAN_MONTHS[2:]],
    ]
    if pending_sub_id is not None:
        rows.append([kb._btn("📤 ارسال / ارسال مجدد رسید", f"pl:rcpt:{pending_sub_id}")])
    rows.append([kb._btn("« بستن", "pl:x")])
    return text, kb._markup(rows)


def render_builder(telegram_user_id: int) -> tuple[str, dict]:
    d = _draft(telegram_user_id)
    if d.get("mode") == "upgrade":
        return render_upgrade_builder(telegram_user_id)

    d["mode"] = "new"
    q = quote_plan(
        int(d["months"]),
        include_ai=bool(d["include_ai"]),
        include_ats=bool(d["include_ats"]),
    )
    discount_note = format_addon_discount_note(q)
    discount_block = f"\n\n{discount_note}" if discount_note else ""
    ai_line = (
        f"+{format_money(q.ai_price, q.currency)}"
        if q.include_ai
        else "(خاموش)"
    )
    ats_line = (
        f"+{format_money(q.ats_price, q.currency)}"
        if q.include_ats
        else "(خاموش)"
    )
    text = (
        "<b>💎 ساخت حساب کاربری</b>\n\n"
        f"⏱ <b>مدت:</b>\n"
        f"{_month_label(q.months)}\n"
        f"پایه: <b>{format_money(q.base_price, q.currency)}</b>\n\n"
        f"🧩 <b>افزونه‌ها:</b>\n"
        f"هوش مصنوعی: {_bool_icon(q.include_ai)} {ai_line}\n"
        f"سیستم امتیازدهی ATS: {_bool_icon(q.include_ats)} {ats_line}"
        f"{discount_block}\n\n"
        f"💰 <b>جمع:</b>\n"
        f"<b>{format_money(q.total, q.currency)}</b>\n\n"
        "بعد از انتخاب موارد بالا دکمه تأیید را بزنید"
    )
    rows = [
        [
            kb._btn(f"{'✅' if m == q.months else '○'} {_month_label(m)}", f"pl:m:{m}")
            for m in PLAN_MONTHS
        ],
        [
            kb._btn(f"{_bool_icon(q.include_ai)} هوش مصنوعی", "pl:t:ai"),
            kb._btn(f"{_bool_icon(q.include_ats)} ATS", "pl:t:ats"),
        ],
        [kb._btn("✅ تأیید", "pl:buy")],
        [kb._btn("« بازگشت", "pl:home")],
    ]
    return text, kb._markup(rows)


def render_order_placed(sub: Subscription) -> tuple[str, dict]:
    if int(sub.months or 0) == 0:
        plan_bit = "افزونه (بدون تمدید)"
        discount_block = ""
    else:
        plan_bit = _month_label(sub.months)
        # Reconstruct quote to show discount that was applied at order time
        try:
            q = quote_plan(
                int(sub.months),
                include_ai=bool(sub.include_ai),
                include_ats=bool(sub.include_ats),
            )
            note = format_addon_discount_note(q)
            discount_block = f"\n{note}\n" if note else ""
        except Exception:
            discount_block = ""
    extra = _extras_label(include_ai=bool(sub.include_ai), include_ats=bool(sub.include_ats))
    text = (
        f"<b>🧾 سفارش #{sub.id}</b> — {plan_bit}{extra}\n"
        f"{discount_block}\n"
        + _card_payment_block(
            amount=float(sub.total_price),
            currency=sub.currency,
            order_id=sub.id,
        )
    )
    rows = [
        [kb._btn("📤 پرداخت کردم — ارسال رسید", f"pl:rcpt:{sub.id}")],
        [kb._btn("« پلن‌ها", "pl:home")],
    ]
    return text, kb._markup(rows)


def render_waiting_receipt(sub: Subscription) -> tuple[str, dict]:
    text = (
        f"<b>📤 ارسال رسید سفارش #{sub.id}</b>\n\n"
        f"💵 مبلغ: <b>{format_money(sub.total_price, sub.currency)}</b>\n\n"
        "عکس رسید کارت‌به‌کارت (یا تصویر/PDF) را بفرستید.\n"
        "برای انصراف روی دکمه لغو بزنید"
    )
    return text, kb._markup([[kb._btn("لغو", f"pl:rcancel:{sub.id}")]])


def render_admin_receipt(
    sub: Subscription,
    *,
    username: str | None,
    first_name: str | None = None,
) -> tuple[str, dict]:
    who = f"@{_esc(username)}" if username else (_esc(first_name) if first_name else f"کاربر #{sub.user_id}")
    if int(sub.months or 0) == 0:
        plan_bit = "افزونه (بدون تمدید)"
    else:
        plan_bit = _month_label(int(sub.months))
    extra = _extras_label(include_ai=bool(sub.include_ai), include_ats=bool(sub.include_ats))
    cur = sub.currency
    detail_lines = [f"💵 پایه: <b>{format_money(sub.base_price, cur)}</b>"]
    if bool(sub.include_ai) or float(sub.ai_price or 0) > 0:
        detail_lines.append(f"🤖 هوش مصنوعی: <b>{format_money(sub.ai_price, cur)}</b>")
    if bool(sub.include_ats) or float(sub.ats_price or 0) > 0:
        detail_lines.append(f"📊 ATS: <b>{format_money(sub.ats_price, cur)}</b>")
    details = "\n".join(detail_lines)
    text = (
        "<b>🧾 رسید کارت‌به‌کارت</b>\n\n"
        f"👤 از: {who}\n"
        f"📦 پلن: <b>{plan_bit}{extra}</b>\n"
        f"🧾 شماره سفارش: <code>{sub.id}</code>\n"
        "💳 روش: کارت‌به‌کارت\n\n"
        f"💰 <b>جزئیات مبلغ:</b>\n"
        f"{details}\n"
        "────────────────\n"
        f"✅ جمع قابل تأیید: <b>{format_money(sub.total_price, cur)}</b>\n\n"
        "رسید بالا را بررسی کنید، سپس فعال یا رد کنید."
    )
    rows = [
        [
            kb._btn("✅ فعال‌سازی", f"pl:adm:ok:{sub.id}"),
            kb._btn("❌ رد", f"pl:adm:no:{sub.id}"),
        ]
    ]
    return text, kb._markup(rows)


async def handle_callback(
    data: str,
    *,
    telegram_user_id: int,
    chat_id: int,
    username: str | None = None,
    first_name: str | None = None,
    is_admin: bool = False,
) -> dict:
    parts = data.split(":")
    if len(parts) < 2:
        return {"toast": "نامشخص"}

    op = parts[1]

    if op == "x":
        clear_draft(telegram_user_id)
        clear_awaiting_receipt(telegram_user_id)
        return {
            "toast": "بسته شد",
            "edit_text": "بسته شد.",
            "reply_markup": kb.cleared_keyboard(),
        }

    if op == "home":
        clear_draft(telegram_user_id)
        text, markup = render_plans_home(telegram_user_id=telegram_user_id)
        return {"toast": "پلن‌ها", "edit_text": text, "reply_markup": markup}

    if op == "status":
        text, markup = render_account_status(telegram_user_id=telegram_user_id)
        return {"toast": "وضعیت حساب", "edit_text": text, "reply_markup": markup}

    if op == "up":
        db = SessionLocal()
        try:
            user = get_user_by_telegram_id(db, telegram_user_id)
            if not user:
                return {
                    "toast": "اول پلن بخرید",
                    "alert": True,
                    "edit_text": (
                        "<b>⬆️ ارتقا</b>\n\n"
                        "هنوز اشتراک فعالی ندارید. اول از 💎 پلن‌ها خرید کنید."
                    ),
                    "reply_markup": kb._markup(
                        [[kb._btn("💎 پلن‌ها", "pl:home")], [kb._btn("« بستن", "pl:x")]]
                    ),
                }
            active = get_active_subscription(db, user.id)
            if not active:
                return {
                    "toast": "اشتراک فعال نیست",
                    "alert": True,
                    "edit_text": (
                        "<b>⬆️ ارتقا</b>\n\n"
                        "اشتراک فعالی ندارید. برای خرید جدید از پلن‌ها استفاده کنید."
                    ),
                    "reply_markup": kb._markup(
                        [[kb._btn("💎 پلن‌ها", "pl:home")], [kb._btn("« بستن", "pl:x")]]
                    ),
                }
            _seed_upgrade_draft(
                telegram_user_id,
                include_ai=bool(active.include_ai),
                include_ats=bool(active.include_ats),
                days_left=_days_left(active.expires_at),
            )
        finally:
            db.close()
        text, markup = render_upgrade_builder(telegram_user_id)
        return {"toast": "ارتقای پلن", "edit_text": text, "reply_markup": markup}

    if op == "m" and len(parts) >= 3:
        try:
            months = int(parts[2])
        except (ValueError, TypeError):
            return {"toast": "مدت نامعتبر", "alert": True}
        d = _draft(telegram_user_id)
        if d.get("mode") == "upgrade":
            if months not in (0, *PLAN_MONTHS):
                return {"toast": "مدت نامعتبر", "alert": True}
            d["months"] = months
            text, markup = render_upgrade_builder(telegram_user_id)
            label = "بدون تمدید" if months == 0 else _month_label(months)
            return {"toast": label, "edit_text": text, "reply_markup": markup}
        try:
            quote_plan(months)
        except (ValueError, TypeError):
            return {"toast": "مدت نامعتبر", "alert": True}
        d["mode"] = "new"
        d["months"] = months
        text, markup = render_builder(telegram_user_id)
        return {"toast": _month_label(months), "edit_text": text, "reply_markup": markup}

    if op == "t" and len(parts) >= 3:
        d = _draft(telegram_user_id)
        if parts[2] == "ai":
            if d.get("mode") == "upgrade" and d.get("locked_ai"):
                return {"toast": "هوش مصنوعی از قبل فعال است", "alert": True}
            d["include_ai"] = not bool(d.get("include_ai"))
        elif parts[2] == "ats":
            if d.get("mode") == "upgrade" and d.get("locked_ats"):
                return {"toast": "ATS از قبل فعال است", "alert": True}
            d["include_ats"] = not bool(d.get("include_ats"))
        else:
            return {"toast": "افزونه نامشخص"}
        text, markup = render_builder(telegram_user_id)
        return {"toast": "به‌روز شد", "edit_text": text, "reply_markup": markup}

    if op == "rcancel" and len(parts) >= 3:
        clear_awaiting_receipt(telegram_user_id)
        try:
            sub_id = int(parts[2])
        except ValueError:
            text, markup = render_plans_home(telegram_user_id=telegram_user_id)
            return {
                "toast": "لغو شد",
                "edit_text": "ارسال رسید لغو شد.",
                "reply_markup": markup,
            }
        db = SessionLocal()
        try:
            sub = db.get(Subscription, sub_id)
            if sub is not None and sub.status in ("pending", "awaiting_confirm"):
                text, markup = render_order_placed(sub)
                return {
                    "toast": "لغو شد",
                    "edit_text": text,
                    "reply_markup": markup,
                }
        finally:
            db.close()
        text, markup = render_plans_home(telegram_user_id=telegram_user_id)
        return {
            "toast": "لغو شد",
            "edit_text": "ارسال رسید لغو شد.",
            "reply_markup": markup,
        }

    if op == "rcpt" and len(parts) >= 3:
        try:
            sub_id = int(parts[2])
        except ValueError:
            return {"toast": "شماره سفارش نامعتبر", "alert": True}
        db = SessionLocal()
        try:
            sub = db.get(Subscription, sub_id)
            if sub is None or sub.status not in ("pending", "awaiting_confirm"):
                return {"toast": "سفارش باز نیست", "alert": True}
            user = get_user_by_telegram_id(db, telegram_user_id)
            if not user or sub.user_id != user.id:
                if not is_admin:
                    return {"toast": "این سفارش مال شما نیست", "alert": True}
            set_awaiting_receipt(telegram_user_id, sub_id)
            text, markup = render_waiting_receipt(sub)
            return {
                "toast": "عکس رسید را بفرستید",
                "edit_text": text,
                "reply_markup": markup,
            }
        finally:
            db.close()

    if op == "buy":
        d = _draft(telegram_user_id)
        db = SessionLocal()
        try:
            user = get_or_create_user(
                db,
                telegram_user_id=telegram_user_id,
                chat_id=chat_id,
                username=username,
                first_name=first_name,
            )
            if d.get("mode") == "upgrade":
                active = get_active_subscription(db, user.id)
                if not active:
                    return {
                        "toast": "اشتراک فعال نیست",
                        "alert": True,
                    }
                try:
                    quote = quote_upgrade(
                        int(d.get("months") or 0),
                        want_ai=bool(d.get("include_ai")),
                        want_ats=bool(d.get("include_ats")),
                        current_ai=bool(d.get("locked_ai")),
                        current_ats=bool(d.get("locked_ats")),
                        days_left=_days_left(active.expires_at),
                    )
                except ValueError as exc:
                    return {"toast": str(exc)[:180], "alert": True}
                sub, _quote = create_pending_subscription(
                    db,
                    user,
                    months=int(quote.months),
                    include_ai=bool(quote.include_ai),
                    include_ats=bool(quote.include_ats),
                    quote=quote,
                )
            else:
                sub, _quote = create_pending_subscription(
                    db,
                    user,
                    months=int(d["months"]),
                    include_ai=bool(d.get("include_ai")),
                    include_ats=bool(d.get("include_ats")),
                )
            clear_draft(telegram_user_id)
            text, markup = render_order_placed(sub)
            return {
                "toast": "پرداخت کارت‌به‌کارت",
                "edit_text": text,
                "reply_markup": markup,
            }
        except Exception as exc:
            logger.exception("Plan order failed")
            return {"toast": f"خطا: {exc}"[:180], "alert": True}
        finally:
            db.close()

    if op == "adm" and len(parts) >= 4:
        if not is_admin:
            return {"toast": "فقط ادمین", "alert": True}
        action = parts[2]
        try:
            sub_id = int(parts[3])
        except ValueError:
            return {"toast": "شماره سفارش نامعتبر", "alert": True}

        from app.database import User

        db = SessionLocal()
        try:
            if action == "ok":
                sub = activate_subscription(db, sub_id, activated_by=f"tg:{telegram_user_id}")
                user = db.get(User, sub.user_id)
                if user:
                    clear_awaiting_receipt(int(user.telegram_user_id))
                extra = _extras_label(
                    include_ai=bool(sub.include_ai), include_ats=bool(sub.include_ats)
                )
                exp = sub.expires_at.strftime("%Y-%m-%d") if sub.expires_at else "—"
                days = _days_left(sub.expires_at)
                month_txt = (
                    "افزونه (بدون تمدید)"
                    if int(sub.months or 0) == 0
                    else _month_label(sub.months)
                )
                user_msg = (
                    f"✅ <b>اشتراک فعال / ارتقا شد</b>\n\n"
                    f"{month_txt}{extra}\n"
                    f"معتبر تا <b>{exp}</b> · <b>{days}</b> روز باقی\n"
                    f"پرداخت (کارت‌به‌کارت): {format_money(sub.total_price, sub.currency)}"
                )
                admin_edit = f"✅ سفارش <code>{sub.id}</code> فعال شد · تا {exp}"
                return {
                    "toast": "فعال شد",
                    "edit_text": admin_edit,
                    "reply_markup": kb.cleared_keyboard(),
                    "notify_user": {
                        "chat_id": user.chat_id if user else None,
                        "telegram_user_id": int(user.telegram_user_id) if user else None,
                        "text": user_msg,
                    },
                }
            if action == "no":
                sub = reject_subscription(db, sub_id)
                user = db.get(User, sub.user_id)
                if user:
                    clear_awaiting_receipt(int(user.telegram_user_id))
                return {
                    "toast": "رد شد",
                    "edit_text": f"❌ سفارش <code>{sub.id}</code> رد شد",
                    "reply_markup": kb.cleared_keyboard(),
                    "notify_user": {
                        "chat_id": user.chat_id if user else None,
                        "telegram_user_id": int(user.telegram_user_id) if user else None,
                        "text": (
                            f"❌ سفارش <code>{sub.id}</code> تأیید نشد "
                            "(رسید کارت‌به‌کارت).\n"
                            "در صورت نیاز از منوی پلن‌ها دوباره سفارش دهید."
                        ),
                    },
                }
            return {"toast": "عملیات نامشخص"}
        except Exception as exc:
            logger.exception("Admin plan action failed")
            return {"toast": f"خطا: {exc}"[:180], "alert": True}
        finally:
            db.close()

    return {"toast": "نامشخص"}


async def handle_receipt_upload(
    *,
    telegram_user_id: int,
    chat_id: int,
    file_id: str,
    username: str | None = None,
    first_name: str | None = None,
    subscription_id: int | None = None,
) -> dict:
    sub_id = subscription_id or awaiting_receipt_subscription_id(telegram_user_id)
    if sub_id is None:
        db = SessionLocal()
        try:
            user = get_user_by_telegram_id(db, telegram_user_id)
            if user:
                pending = get_pending_subscription(db, user.id)
                if pending:
                    sub_id = pending.id
        finally:
            db.close()
    if sub_id is None:
        return {
            "handled": False,
            "message": "سفارش بازی ندارید. اول از 💎 پلن‌ها سفارش بدهید، بعد رسید را بفرستید.",
        }

    db = SessionLocal()
    try:
        user = get_or_create_user(
            db,
            telegram_user_id=telegram_user_id,
            chat_id=chat_id,
            username=username,
            first_name=first_name,
        )
        sub = db.get(Subscription, sub_id)
        if sub is None or sub.user_id != user.id:
            return {"handled": True, "message": "❌ این سفارش مال شما نیست یا لغو شده است."}
        if sub.status not in ("pending", "awaiting_confirm"):
            return {"handled": True, "message": "❌ این سفارش دیگر منتظر پرداخت نیست."}

        sub = attach_receipt(db, sub.id, receipt_file_id=file_id)
        clear_awaiting_receipt(telegram_user_id)
        admin_text, admin_markup = render_admin_receipt(
            sub, username=username, first_name=first_name
        )
        return {
            "handled": True,
            "message": (
                f"✅ رسید سفارش <code>{sub.id}</code> دریافت شد.\n"
                "منتظر تأیید ادمین برای پرداخت بمانید."
            ),
            "notify_admin_receipt": {
                "file_id": file_id,
                "caption": admin_text,
                "reply_markup": admin_markup,
            },
        }
    except Exception as exc:
        logger.exception("Receipt upload failed")
        return {"handled": True, "message": f"❌ ذخیره رسید ممکن نشد: {exc}"}
    finally:
        db.close()
