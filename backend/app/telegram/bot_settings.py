"""Telegram bot settings — LinkedIn Job Finder only (Farsi UI)."""

from __future__ import annotations

import html
import logging
from typing import Any

from app.database import SessionLocal
from app.telegram import keyboards as kb

logger = logging.getLogger(__name__)

_pending_edits: dict[str, dict[str, str]] = {}

PROVIDERS = ("groq", "gemini", "deepseek", "openai", "anthropic")

# Short callback field codes -> (category, setting_key, label, type)
FIELDS: dict[str, tuple[str, str, str, str]] = {
    # General
    "test": ("gen", "test_mode", "حالت آزمایشی", "toggle"),
    "auto": ("gen", "automation_enabled", "اتوماسیون", "toggle"),
    # AI
    "scr": ("ai", "ai_screening_provider", "ارائه‌دهنده غربالگری", "pick_provider"),
    "prop": ("ai", "ai_proposal_provider", "ارائه‌دهنده نوشتن", "pick_provider"),
    # LinkedIn
    "lien": ("li", "li_enabled", "جستجوی لینکدین", "toggle"),
    "limail": ("li", "li_auto_mailing", "ارسال خودکار ایمیل", "toggle"),
    "litest": ("li", "li_test_mode", "حالت آزمایشی لینکدین", "toggle"),
    "lipoll": ("li", "li_poll", "فاصله جستجو (دقیقه)", "int"),
    "limax": ("li", "li_max_emails", "حداکثر ایمیل در روز", "int"),
    "lilist": ("li", "li_list_thr", "آستانه تطابق لیست %", "int"),
    "liemail": ("li", "li_email_thr", "آستانه تطابق ایمیل %", "int"),
    "liats": ("li", "li_ats_thr", "آستانه رزومه ATS %", "int"),
    "liloc": ("li", "li_location", "مکان جستجو", "text"),
    "lisp": ("li", "li_search", "عبارات جستجو (با ویرگول)", "list"),
    "ligmail": ("li", "li_gmail", "آدرس جیمیل", "text"),
    "ligpwd": ("li", "li_gmail_pwd", "رمز اپ جیمیل (App Password)", "secret"),
}


def pending_for(chat_id: int | str) -> dict[str, str] | None:
    return _pending_edits.get(str(chat_id))


def clear_pending(chat_id: int | str) -> None:
    _pending_edits.pop(str(chat_id), None)


def set_pending(chat_id: int | str, field_code: str) -> str:
    meta = FIELDS.get(field_code)
    if not meta:
        raise ValueError("فیلد نامشخص")
    _, _, label, kind = meta
    _pending_edits[str(chat_id)] = {
        "field": field_code,
        "label": label,
        "kind": kind,
    }
    return label


def _bool_icon(v: bool) -> str:
    return "✅" if v else "❌"


def _esc(v: Any) -> str:
    return html.escape(str(v if v is not None else "—"))


def render_home() -> tuple[str, dict]:
    from app.config import settings
    from app.linkedin.settings import load_linkedin_settings
    from app.worker.queue import worker_status

    db = SessionLocal()
    try:
        ws = worker_status(db)
        li = load_linkedin_settings(db)
    finally:
        db.close()

    text = (
        "<b>⚙️ تنظیمات</b>\n\n"
        f"حالت آزمایشی: {_bool_icon(settings.test_mode)}\n"
        f"اتوماسیون: {_bool_icon(settings.automation_enabled)}\n"
        f"جستجوی لینکدین: {_bool_icon(li.enabled)}\n"
        f"صف کار سنگین: {_bool_icon(ws.get('queue_heavy_work'))}\n"
        f"ورکر PC: {_bool_icon(ws.get('worker_online'))}"
        f"{' · ' + str(ws.get('pending', 0)) + ' در صف' if ws.get('pending') else ''}\n\n"
        "<b>مسیر شغل</b>\n"
        "۱. جستجو و فیلتر\n"
        "۲. جیمیل ارسال\n"
        "۳. بررسی شغل‌ها از منوی <b>💼 شغل‌های جدید</b>\n\n"
        "یک بخش را انتخاب کنید:"
    )
    return text, kb.settings_home_keyboard()


def render_category(cat: str) -> tuple[str, dict]:
    if cat == "plan":
        from app.billing import bot_plans

        return bot_plans.render_plans_home(telegram_user_id=None)
    if cat == "gen":
        return _render_general()
    if cat == "ai":
        return _render_ai()
    if cat == "li":
        return _render_linkedin()
    if cat == "st":
        return _render_status()
    return render_home()


def _render_general() -> tuple[str, dict]:
    from app.config import settings

    text = (
        "<b>⚙️ عمومی</b>\n\n"
        f"حالت آزمایشی: {_bool_icon(settings.test_mode)} — AI کار می‌کند ولی ایمیل واقعی ارسال نمی‌شود\n"
        f"اتوماسیون: {_bool_icon(settings.automation_enabled)}\n\n"
        "برای تغییر روی دکمه بزنید:"
    )
    rows = [
        [
            kb._btn(f"{_bool_icon(settings.test_mode)} حالت آزمایشی", "s:t:test"),
            kb._btn(f"{_bool_icon(settings.automation_enabled)} اتوماسیون", "s:t:auto"),
        ],
        [kb._btn("« بازگشت", "s:m")],
    ]
    return text, kb._markup(rows)


def _render_ai() -> tuple[str, dict]:
    from app.config import settings

    text = (
        "<b>🤖 هوش مصنوعی</b>\n\n"
        f"پیش‌فرض: <b>{_esc(settings.ai_provider)}</b>\n"
        f"غربالگری: <b>{_esc(settings.screening_provider)}</b> / {_esc(settings.screening_model())}\n"
        f"نوشتن: <b>{_esc(settings.proposal_provider)}</b> / {_esc(settings.proposal_model())}\n\n"
        "برای تغییر ارائه‌دهنده روی دکمه بزنید "
        "(کلید API را در .env بگذارید).\n"
        "همچنین از «مدیریت فروش» می‌توانید ارائه‌دهنده را عوض کنید."
    )
    rows = [
        [kb._btn(f"غربالگری: {settings.screening_provider}", "s:e:scr")],
        [kb._btn(f"نوشتن: {settings.proposal_provider}", "s:e:prop")],
        [kb._btn("« بازگشت", "s:m")],
    ]
    return text, kb._markup(rows)


def _render_provider_pick(field_code: str) -> tuple[str, dict]:
    meta = FIELDS[field_code]
    label = meta[2]
    text = f"<b>انتخاب {html.escape(label)}</b>"
    rows = []
    row: list[dict] = []
    for p in PROVIDERS:
        row.append(kb._btn(p, f"s:p:{field_code}:{p}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([kb._btn("« بازگشت", f"s:c:{meta[0]}")])
    return text, kb._markup(rows)


def _render_linkedin() -> tuple[str, dict]:
    from app.linkedin.settings import load_linkedin_settings

    db = SessionLocal()
    try:
        cfg = load_linkedin_settings(db)
    finally:
        db.close()

    from app.linkedin.email_send import gmail_configured

    phrases = ", ".join(cfg.search_phrases[:5])
    if len(cfg.search_phrases) > 5:
        phrases += "…"
    gmail_addr = (cfg.gmail_address or "").strip()
    gmail_ready = gmail_configured(cfg)
    gmail_line = (
        f"جیمیل: {_bool_icon(gmail_ready)} "
        f"<code>{_esc(gmail_addr or 'تنظیم نشده')}</code>"
        if gmail_addr
        else f"جیمیل: {_bool_icon(False)} تنظیم نشده"
    )
    pwd_line = (
        f"رمز اپ: {_bool_icon(bool((cfg.gmail_app_password or '').strip()))} "
        + ("ذخیره شده" if (cfg.gmail_app_password or "").strip() else "تنظیم نشده")
    )
    text = (
        "<b>🔗 جستجو و فیلتر</b>\n\n"
        f"جستجو: {_bool_icon(cfg.enabled)}\n"
        f"ارسال خودکار ایمیل: {_bool_icon(cfg.auto_mailing_enabled)}\n"
        f"حالت آزمایشی: {_bool_icon(cfg.test_mode)}\n"
        f"{gmail_line}\n"
        f"{pwd_line}\n"
        f"فاصله جستجو: <b>{cfg.poll_interval_minutes}</b> دقیقه · "
        f"حداکثر ایمیل: <b>{cfg.max_emails_per_day}</b>\n"
        f"آستانه تطابق — لیست <b>{cfg.list_cv_match_threshold}%</b> · "
        f"ایمیل <b>{cfg.email_cv_match_threshold}%</b> · "
        f"ATS <b>{cfg.ats_resume_threshold}%</b>\n"
        f"مکان: <code>{_esc(cfg.location or '—')}</code>\n"
        f"عبارات جستجو: <code>{_esc(phrases or '—')}</code>\n\n"
        "<i>برای ارسال ایمیل درخواست شغل، جیمیل و App Password را تنظیم کنید.</i>"
    )
    rows = [
        [
            kb._btn(f"{_bool_icon(cfg.enabled)} جستجو", "s:t:lien"),
            kb._btn(f"{_bool_icon(cfg.auto_mailing_enabled)} ایمیل خودکار", "s:t:limail"),
        ],
        [kb._btn(f"{_bool_icon(cfg.test_mode)} حالت آزمایشی", "s:t:litest")],
        [
            kb._btn("📧 آدرس جیمیل", "s:e:ligmail"),
            kb._btn("🔑 رمز اپ جیمیل", "s:e:ligpwd"),
        ],
        [kb._btn("🔌 تست اتصال جیمیل", "s:g:test")],
        [
            kb._btn(f"فاصله {cfg.poll_interval_minutes}د", "s:e:lipoll"),
            kb._btn(f"حداکثر {cfg.max_emails_per_day}/روز", "s:e:limax"),
        ],
        [
            kb._btn(f"لیست {cfg.list_cv_match_threshold}%", "s:e:lilist"),
            kb._btn(f"ایمیل {cfg.email_cv_match_threshold}%", "s:e:liemail"),
            kb._btn(f"ATS {cfg.ats_resume_threshold}%", "s:e:liats"),
        ],
        [
            kb._btn("مکان", "s:e:liloc"),
            kb._btn("عبارات جستجو", "s:e:lisp"),
        ],
        [kb._btn("« بازگشت", "s:m")],
    ]
    return text, kb._markup(rows)


def _render_status() -> tuple[str, dict]:
    from app.linkedin import token_store as li_token_store
    from app.telegram.service import telegram_service
    from app.worker.queue import worker_status

    db = SessionLocal()
    try:
        li = li_token_store.is_connected(db)
        ws = worker_status(db)
    finally:
        db.close()

    text = (
        "<b>📡 وضعیت</b> <i>(فقط مشاهده)</i>\n\n"
        f"ربات تلگرام: {_bool_icon(True)}\n"
        f"لینکدین OAuth: {_bool_icon(li)}\n"
        f"صف کار سنگین: {_bool_icon(ws.get('queue_heavy_work'))}\n"
        f"ورکر PC: {_bool_icon(ws.get('worker_online'))}\n"
        f"صف: {ws.get('pending', 0)} در انتظار · {ws.get('claimed', 0)} در حال انجام\n"
    )
    return text, kb._markup(
        [[kb._btn("« بازگشت", "s:m")], [kb._btn("تازه‌سازی", "s:c:st")]]
    )


async def handle_callback(data: str, chat_id: int | str) -> dict:
    """Handle s:* callbacks."""
    parts = data.split(":")
    if len(parts) < 2:
        return {"toast": "نامشخص"}

    op = parts[1]

    if op == "m" or data == "s:m":
        clear_pending(chat_id)
        text, markup = render_home()
        return {"toast": "تنظیمات", "edit_text": text, "reply_markup": markup}

    if op == "c" and len(parts) >= 3:
        clear_pending(chat_id)
        text, markup = render_category(parts[2])
        return {"toast": "باشه", "edit_text": text, "reply_markup": markup}

    if op == "t" and len(parts) >= 3:
        field = parts[2]
        if field not in FIELDS:
            return {"toast": "فیلد نامشخص", "alert": True}
        try:
            await _toggle(field)
        except Exception as exc:
            logger.exception("Toggle failed")
            return {"toast": f"خطا: {exc}"[:180], "alert": True}
        cat = FIELDS[field][0]
        text, markup = render_category(cat)
        return {"toast": "به‌روز شد", "edit_text": text, "reply_markup": markup}

    if op == "e" and len(parts) >= 3:
        field = parts[2]
        meta = FIELDS.get(field)
        if not meta:
            return {"toast": "فیلد نامشخص"}
        if meta[3] == "pick_provider":
            text, markup = _render_provider_pick(field)
            return {"toast": "انتخاب کنید", "edit_text": text, "reply_markup": markup}
        label = set_pending(chat_id, field)
        kind = meta[3]
        hint = {
            "int": "یک عدد صحیح بفرستید.",
            "float": "یک عدد بفرستید (یا برای خالی کردن: clear).",
            "text": "متن جدید را بفرستید.",
            "list": "مقادیر را با ویرگول جدا کنید.",
            "secret": (
                "رمز ۱۶ کاراکتری <b>App Password</b> جیمیل را بفرستید "
                "(فاصله‌ها حذف می‌شوند).\n"
                "مسیر ساخت: Google Account → Security → App passwords"
            ),
        }.get(kind, "مقدار جدید را بفرستید.")
        if field == "ligmail":
            hint = (
                "آدرس جیمیل خود را بفرستید، مثلاً:\n"
                "<code>name@gmail.com</code>\n"
                "IMAP باید در تنظیمات جیمیل روشن باشد."
            )
        return {
            "toast": "منتظر مقدار…",
            "prompt": (
                f"✏️ <b>{html.escape(label)}</b>\n\n"
                f"{hint}\n"
                "برای انصراف: <code>لغو</code>"
            ),
        }

    if op == "g" and len(parts) >= 3 and parts[2] == "test":
        from app.linkedin.email_send import gmail_configured, test_connection
        from app.linkedin.settings import load_linkedin_settings

        db = SessionLocal()
        try:
            cfg = load_linkedin_settings(db)
        finally:
            db.close()
        if not gmail_configured(cfg):
            return {
                "toast": "جیمیل هنوز کامل نیست",
                "alert": True,
                "prompt": (
                    "❌ ابتدا <b>آدرس جیمیل</b> و <b>رمز اپ</b> را تنظیم کنید، "
                    "بعد دوباره تست را بزنید."
                ),
            }
        ok, err = test_connection(cfg.gmail_address, cfg.gmail_app_password)
        if ok:
            text, markup = _render_linkedin()
            return {
                "toast": "اتصال جیمیل OK",
                "prompt": (
                    f"✅ اتصال SMTP جیمیل موفق بود.\n"
                    f"حساب: <code>{_esc(cfg.gmail_address)}</code>"
                ),
                "edit_text": text,
                "reply_markup": markup,
            }
        return {
            "toast": "اتصال ناموفق",
            "alert": True,
            "prompt": f"❌ اتصال جیمیل ناموفق:\n{_esc(err or 'خطای نامشخص')}",
        }

    if op == "p" and len(parts) >= 4:
        field, value = parts[2], parts[3]
        if field not in FIELDS:
            return {"toast": "فیلد نامشخص", "alert": True}
        try:
            await _set_provider(field, value)
        except Exception as exc:
            return {"toast": f"خطا: {exc}"[:180], "alert": True}
        cat = FIELDS[field][0]
        text, markup = render_category(cat)
        return {"toast": f"تنظیم شد: {value}", "edit_text": text, "reply_markup": markup}

    return {"toast": "عملیات نامشخص"}


async def handle_text_value(chat_id: int | str, text: str) -> dict:
    """Apply pending edit from a user message."""
    pending = pending_for(chat_id)
    if not pending:
        return {"handled": False}

    raw = (text or "").strip()
    if raw.lower() in ("cancel", "/cancel", "لغو", "انصراف"):
        clear_pending(chat_id)
        home, markup = render_home()
        return {
            "handled": True,
            "message": "لغو شد.",
            "follow_up": home,
            "reply_markup": markup,
        }

    field = pending["field"]
    kind = pending["kind"]

    try:
        value = _parse_value(raw, kind)
        await _apply_field(field, value)
    except Exception as exc:
        return {
            "handled": True,
            "message": (
                f"❌ {html.escape(str(exc))}\n"
                "مقدار جدید بفرستید یا <code>لغو</code> کنید."
            ),
        }

    clear_pending(chat_id)
    cat = FIELDS[field][0]
    body, markup = render_category(cat)
    # Never echo secrets back into the chat.
    if kind == "secret" or field == "ligpwd":
        confirm = f"✅ <b>{html.escape(pending['label'])}</b> ذخیره شد."
    elif field == "ligmail":
        confirm = (
            f"✅ <b>{html.escape(pending['label'])}</b> به‌روز شد:\n"
            f"<code>{_esc(value)}</code>\n\n"
            "اگر هنوز رمز اپ را نگذاشته‌اید، دکمه <b>🔑 رمز اپ جیمیل</b> را بزنید."
        )
    else:
        confirm = f"✅ <b>{html.escape(pending['label'])}</b> به‌روز شد."
    return {
        "handled": True,
        "message": confirm,
        "follow_up": body,
        "reply_markup": markup,
        "delete_user_message": kind == "secret" or field == "ligpwd",
    }


async def handle_document_upload(chat_id: int | str, content: str, filename: str = "") -> dict:
    """Legacy guide upload — no longer used for LinkedIn product."""
    return {"handled": False}


def _parse_value(raw: str, kind: str) -> Any:
    if kind == "int":
        if not raw.isdigit() and not (raw.startswith("-") and raw[1:].isdigit()):
            raise ValueError("یک عدد صحیح لازم است")
        return int(raw)
    if kind == "float":
        if raw.lower() in ("", "none", "clear", "-", "خالی"):
            return None
        return float(raw.replace(",", "").replace("،", ""))
    if kind in ("text", "list", "secret"):
        return raw
    raise ValueError(f"این نوع فیلد با متن قابل ویرایش نیست ({kind})")


async def _toggle(field_code: str) -> None:
    meta = FIELDS[field_code]
    key = meta[1]
    db = SessionLocal()
    try:
        if key == "test_mode":
            from app.config import settings
            from app.services.settings_service import persist_setting

            settings.test_mode = not settings.test_mode
            persist_setting(db, "test_mode", "true" if settings.test_mode else "false")
        elif key == "automation_enabled":
            from app.config import settings
            from app.services.settings_service import persist_setting
            from app.telegram.service import telegram_service

            settings.automation_enabled = not settings.automation_enabled
            telegram_service.set_automation_enabled(settings.automation_enabled)
            persist_setting(
                db, "automation_enabled", "true" if settings.automation_enabled else "false"
            )
        elif key == "li_enabled":
            from app.linkedin.settings import load_linkedin_settings, save_linkedin_settings

            cfg = load_linkedin_settings(db)
            cfg.enabled = not cfg.enabled
            save_linkedin_settings(db, cfg)
        elif key == "li_auto_mailing":
            from app.linkedin.settings import load_linkedin_settings, save_linkedin_settings

            cfg = load_linkedin_settings(db)
            cfg.auto_mailing_enabled = not cfg.auto_mailing_enabled
            save_linkedin_settings(db, cfg)
        elif key == "li_test_mode":
            from app.linkedin.settings import load_linkedin_settings, save_linkedin_settings

            cfg = load_linkedin_settings(db)
            cfg.test_mode = not cfg.test_mode
            save_linkedin_settings(db, cfg)
        else:
            raise ValueError(f"قابل تغییر نیست: {key}")
    finally:
        db.close()


async def _set_provider(field_code: str, provider: str) -> None:
    provider = provider.lower().strip()
    if provider not in PROVIDERS:
        raise ValueError("ارائه‌دهنده نامعتبر")
    from app.config import settings
    from app.services.settings_service import persist_setting

    db = SessionLocal()
    try:
        if field_code == "scr":
            settings.ai_screening_provider = provider
            persist_setting(db, "ai_screening_provider", provider)
        elif field_code == "prop":
            settings.ai_proposal_provider = provider
            persist_setting(db, "ai_proposal_provider", provider)
        else:
            raise ValueError("فیلد ارائه‌دهنده نامشخص")
    finally:
        db.close()


async def _apply_field(field_code: str, value: Any) -> None:
    meta = FIELDS[field_code]
    key = meta[1]
    db = SessionLocal()
    try:
        if key == "li_poll":
            from app.linkedin.settings import load_linkedin_settings, save_linkedin_settings

            cfg = load_linkedin_settings(db)
            cfg.poll_interval_minutes = max(5, min(1440, int(value)))
            save_linkedin_settings(db, cfg)
        elif key == "li_max_emails":
            from app.linkedin.settings import load_linkedin_settings, save_linkedin_settings

            cfg = load_linkedin_settings(db)
            cfg.max_emails_per_day = max(1, min(100, int(value)))
            save_linkedin_settings(db, cfg)
        elif key == "li_list_thr":
            from app.linkedin.settings import load_linkedin_settings, save_linkedin_settings

            cfg = load_linkedin_settings(db)
            cfg.list_cv_match_threshold = max(0, min(100, int(value)))
            save_linkedin_settings(db, cfg)
        elif key == "li_email_thr":
            from app.linkedin.settings import load_linkedin_settings, save_linkedin_settings

            cfg = load_linkedin_settings(db)
            cfg.email_cv_match_threshold = max(0, min(100, int(value)))
            save_linkedin_settings(db, cfg)
        elif key == "li_ats_thr":
            from app.linkedin.settings import load_linkedin_settings, save_linkedin_settings

            cfg = load_linkedin_settings(db)
            cfg.ats_resume_threshold = max(0, min(100, int(value)))
            save_linkedin_settings(db, cfg)
        elif key == "li_location":
            from app.linkedin.settings import load_linkedin_settings, save_linkedin_settings

            cfg = load_linkedin_settings(db)
            cfg.location = str(value).strip()
            save_linkedin_settings(db, cfg)
        elif key == "li_search":
            from app.linkedin.settings import load_linkedin_settings, save_linkedin_settings

            cfg = load_linkedin_settings(db)
            cfg.search_phrases = [p.strip() for p in str(value).split(",") if p.strip()]
            save_linkedin_settings(db, cfg)
        elif key == "li_gmail":
            from app.linkedin.settings import load_linkedin_settings, save_linkedin_settings

            addr = str(value).strip()
            if "@" not in addr or "." not in addr.split("@")[-1]:
                raise ValueError("آدرس جیمیل معتبر نیست")
            cfg = load_linkedin_settings(db)
            cfg.gmail_address = addr
            cfg.from_email = addr
            save_linkedin_settings(db, cfg)
        elif key == "li_gmail_pwd":
            from app.linkedin.settings import load_linkedin_settings, save_linkedin_settings

            pwd = str(value).strip().replace(" ", "")
            if len(pwd) < 12:
                raise ValueError("App Password کوتاه است — رمز ۱۶ کاراکتری گوگل را بفرستید")
            cfg = load_linkedin_settings(db)
            cfg.gmail_app_password = pwd
            save_linkedin_settings(db, cfg)
        else:
            raise ValueError(f"قابل تنظیم نیست: {key}")
    finally:
        db.close()
