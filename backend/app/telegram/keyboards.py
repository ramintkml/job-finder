"""Inline keyboard builders for the review bot (Farsi UI)."""

from __future__ import annotations


def _btn(text: str, data: str) -> dict:
    return {"text": text, "callback_data": data}


def _row(*buttons: dict) -> list[dict]:
    return list(buttons)


def _markup(rows: list[list[dict]]) -> dict:
    return {"inline_keyboard": rows}


def main_reply_keyboard(
    *,
    include_admin: bool = True,
    telegram_user_id: int | None = None,
    include_ai: bool | None = None,
    include_ats: bool | None = None,
) -> dict:
    """Persistent bottom keyboard — only the JD paste shortcut.

    Everything else lives in the slash-command menu beside the text field
    (see ReviewBot._sync_bot_commands). Extra kwargs kept for call-site compat.
    """
    _ = (include_admin, telegram_user_id, include_ai, include_ats)
    return {
        "keyboard": [
            [{"text": "📋 ارسال آگهی"}, {"text": "🖥 PC Worker"}],
            [{"text": "📄 رزومه پایه"}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def pending_list_keyboard(items: list[tuple[str, str]]) -> dict:
    """Inline list: each item is (button_label, callback_data)."""
    rows = [_row(_btn(label[:64], data)) for label, data in items]
    return _markup(rows)


def settings_home_keyboard() -> dict:
    """Settings hub ordered around job discovery → mail → tools."""
    return _markup(
        [
            _row(_btn("🔍 جستجو و فیلتر", "s:c:li")),
            _row(_btn("📧 جیمیل", "s:c:li")),
            _row(_btn("🤖 هوش مصنوعی", "s:c:ai"), _btn("⚙️ عمومی", "s:c:gen")),
            _row(_btn("📡 وضعیت سیستم", "s:c:st"), _btn("💎 پلن‌ها", "s:c:plan")),
        ]
    )


def project_review_keyboard(project_id: int, *, api_source: bool) -> dict:
    send_label = "ارسال پیشنهاد"
    return _markup(
        [
            _row(
                _btn(f"✅ {send_label}", f"p:s:{project_id}"),
                _btn("⏭ رد کردن", f"p:k:{project_id}"),
            )
        ]
    )


def linkedin_job_keyboard(job_id: int, job_url: str | None = None) -> dict:
    """Per-job actions: view → apply materials → skip."""
    rows: list[list[dict]] = []
    if job_url and job_url.strip().startswith("http"):
        rows.append([{"text": "🔗 مشاهده آگهی", "url": job_url.strip()}])
    rows.append(
        _row(
            _btn("✉ ساخت ایمیل", f"j:c:{job_id}"),
            _btn("📄 ساخت رزومه", f"j:r:{job_id}"),
        )
    )
    rows.append(_row(_btn("⏭ رد کردن", f"j:k:{job_id}")))
    return _markup(rows)


def ats_resume_keyboard(ats_id: int) -> dict:
    return _markup([_row(_btn("🔄 ساخت مجدد", f"a:g:{ats_id}"))])


def resource_alert_keyboard() -> dict:
    return _markup([_row(_btn("🔄 بررسی مجدد", "sys:retest"))])


def cleared_keyboard() -> dict:
    """Empty keyboard to remove buttons after an action."""
    return _markup([])
