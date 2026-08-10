"""Telegram Bot API client for review notifications (inline buttons).

Replaces the three Telethon review channels when TELEGRAM_REVIEW_BOT_TOKEN
and TELEGRAM_REVIEW_CHAT_ID are set. Telethon remains for @KayaProjectsBot bidding.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"

SETTINGS_BUTTON_LABELS = {
    "⚙️ تنظیمات",
    "تنظیمات",
    "/settings",
}

ADMIN_SALES_LABELS = {
    "🛠 مدیریت فروش",
    "مدیریت فروش",
    "/admin",
    "/sales",
}

PLANS_BUTTON_LABELS = {
    "💎 پلن‌ها",
    "پلن‌ها",
    "پلن ها",
    "/plans",
    "/plan",
}

ACCOUNT_STATUS_LABELS = {
    "📋 وضعیت حساب",
    "وضعیت حساب",
    "📋 حساب من",
    "حساب من",
    "/status",
    "/account",
}

UPGRADE_PLAN_LABELS = {
    "⬆️ ارتقای پلن",
    "ارتقای پلن",
    "ارتقا پلن",
    "/upgrade",
}

START_LABELS = {
    "/start",
    "start",
    "شروع",
}

RESOURCE_WATCH_LABELS = {
    "📊 وضعیت منابع",
    "وضعیت منابع",
    "/resources",
    "/resource",
}

SEARCH_SETUP_LABELS = {
    "🔍 تنظیم جستجو",
    "تنظیم جستجو",
    "/search",
    "/search_setup",
}

GMAIL_SETUP_LABELS = {
    "📧 جیمیل",
    "جیمیل",
    "/gmail",
    "/email_setup",
}


class ReviewBot:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._poll_task: asyncio.Task | None = None
        self._offset = 0
        self._running = False
        self._me: dict | None = None
        self._delete_tasks: set[asyncio.Task] = set()

    @property
    def configured(self) -> bool:
        """Bot runs for all users when token is set (normal multi-user bot)."""
        return bool(settings.telegram_review_bot_token.strip())

    @property
    def chat_id(self) -> str:
        """Optional admin chat — card-to-card receipts / alerts only (not a user gate)."""
        return settings.telegram_review_chat_id.strip()

    @property
    def admin_configured(self) -> bool:
        return bool(self.configured and self.chat_id)

    def _url(self, method: str) -> str:
        token = settings.telegram_review_bot_token.strip()
        return f"{API_BASE}/bot{token}/{method}"

    async def start(self) -> None:
        if not self.configured:
            logger.info(
                "Review bot not configured — skipping (set TELEGRAM_REVIEW_BOT_TOKEN)"
            )
            return
        if self._running:
            return
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0))
        self._running = True
        try:
            me = await self._api("getMe")
            self._me = me
            logger.info(
                "Review bot started as @%s (multi-user; admin_chat=%s)",
                (me or {}).get("username") or "?",
                self.chat_id or "(none)",
            )
        except Exception:
            logger.exception("Review bot getMe failed — check TELEGRAM_REVIEW_BOT_TOKEN")
            await self.stop()
            return
        try:
            await self._sync_bot_commands()
        except Exception:
            logger.exception("Failed to set bot command menu")
        # Drop pending updates so we don't replay old callbacks on restart
        try:
            await self._api("getUpdates", {"offset": -1, "limit": 1, "timeout": 0})
        except Exception:
            pass
        # Do not push a message to every user on restart — each user gets /start themselves.
        if self.admin_configured:
            try:
                await self.send_message(
                    "ربات <b>جستجوی شغل لینکدین</b> آنلاین است "
                    "(حالت چندکاربره).\n"
                    "رسیدهای کارت‌به‌کارت اینجا می‌آید.",
                    chat_id=self.chat_id,
                    reply_markup=None,
                )
            except Exception:
                logger.exception("Failed to notify admin chat on startup")
        self._poll_task = asyncio.create_task(self._poll_loop(), name="review-bot-poll")

    async def _sync_bot_commands(self) -> None:
        """Register the slash-command menu shown beside the text field."""
        commands = [
            {"command": "start", "description": "شروع و راهنما"},
            {"command": "apply", "description": "ارسال آگهی شغل (JD) → ارزیابی + رزومه"},
            {"command": "worker", "description": "وضعیت آنلاین بودن PC Worker"},
            {"command": "jobs", "description": "شغل‌های جدید برای بررسی"},
            {"command": "search", "description": "تنظیم جستجوی لینکدین"},
            {"command": "gmail", "description": "راه‌اندازی و وضعیت جیمیل"},
            {"command": "account", "description": "حساب من و اشتراک"},
            {"command": "plans", "description": "پلن‌ها و خرید"},
            {"command": "upgrade", "description": "ارتقای پلن"},
            {"command": "resume", "description": "ساخت رزومه با AI"},
            {"command": "ats", "description": "بررسی ATS رزومه"},
            {"command": "settings", "description": "تنظیمات پیشرفته"},
            {"command": "resources", "description": "وضعیت منابع سیستم"},
            {"command": "admin", "description": "مدیریت فروش (ادمین)"},
        ]
        await self._api("setMyCommands", {"commands": commands})
        # Ensure the menu button next to the text field opens commands
        await self._api(
            "setChatMenuButton",
            {"menu_button": {"type": "commands"}},
        )
        logger.info("Bot command menu synced (%s commands)", len(commands))

    async def stop(self) -> None:
        self._running = False
        for task in list(self._delete_tasks):
            task.cancel()
        self._delete_tasks.clear()
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _api(self, method: str, payload: dict | None = None) -> Any:
        if not self._client:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0))
        resp = await self._client.post(self._url(method), json=payload or {})
        data = resp.json()
        if not data.get("ok"):
            desc = data.get("description") or resp.text
            raise RuntimeError(f"Telegram Bot API {method} failed: {desc}")
        return data.get("result")

    async def send_message(
        self,
        text: str,
        *,
        chat_id: int | str | None = None,
        reply_markup: dict | None = None,
        parse_mode: str | None = "HTML",
        disable_web_page_preview: bool = True,
    ) -> dict | None:
        if not self.configured:
            return None
        target = chat_id if chat_id is not None else self.chat_id
        if not target:
            return None
        payload: dict[str, Any] = {
            "chat_id": target,
            "text": text,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        try:
            return await self._api("sendMessage", payload)
        except Exception:
            logger.exception("Review bot sendMessage failed")
            return None

    async def send_photo(
        self,
        photo_file_id: str,
        *,
        chat_id: int | str | None = None,
        caption: str = "",
        reply_markup: dict | None = None,
        parse_mode: str = "HTML",
    ) -> dict | None:
        if not self.configured:
            return None
        target = chat_id if chat_id is not None else self.chat_id
        if not target:
            return None
        payload: dict[str, Any] = {
            "chat_id": target,
            "photo": photo_file_id,
            "disable_notification": False,
        }
        if caption:
            payload["caption"] = caption[:1024]
            payload["parse_mode"] = parse_mode
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        try:
            return await self._api("sendPhoto", payload)
        except Exception:
            logger.exception("Review bot sendPhoto failed")
            # Fallback: try as document (PDF receipts)
            try:
                payload_doc: dict[str, Any] = {
                    "chat_id": target,
                    "document": photo_file_id,
                }
                if caption:
                    payload_doc["caption"] = caption[:1024]
                    payload_doc["parse_mode"] = parse_mode
                if reply_markup is not None:
                    payload_doc["reply_markup"] = reply_markup
                return await self._api("sendDocument", payload_doc)
            except Exception:
                logger.exception("Review bot sendDocument (receipt) failed")
                return None

    async def send_document(
        self,
        file_path: str | Path,
        *,
        chat_id: int | str | None = None,
        caption: str = "",
        reply_markup: dict | None = None,
        parse_mode: str = "HTML",
    ) -> dict | None:
        if not self.configured:
            return None
        path = Path(file_path)
        if not path.exists():
            logger.error("Review bot sendDocument — file missing: %s", path)
            return None
        target = chat_id if chat_id is not None else self.chat_id
        if not target:
            return None
        if not self._client:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0))
        data = {
            "chat_id": target,
            "parse_mode": parse_mode,
        }
        if caption:
            # Never mid-cut HTML (breaks <blockquote>); caption builders stay under 900
            data["caption"] = caption if len(caption) <= 900 else "ATS resume ready."
            if len(caption) > 900:
                data.pop("parse_mode", None)
        if reply_markup is not None:
            import json

            data["reply_markup"] = json.dumps(reply_markup)
        try:
            with path.open("rb") as fh:
                resp = await self._client.post(
                    self._url("sendDocument"),
                    data=data,
                    files={"document": (path.name, fh)},
                )
            body = resp.json()
            if not body.get("ok"):
                desc = body.get("description") or resp.text
                # Retry once with a plain short caption if HTML caption fails
                if caption and "parse entities" in str(desc).lower():
                    data["caption"] = "ATS resume ready."
                    data.pop("parse_mode", None)
                    with path.open("rb") as fh:
                        resp = await self._client.post(
                            self._url("sendDocument"),
                            data=data,
                            files={"document": (path.name, fh)},
                        )
                    body = resp.json()
                    if body.get("ok"):
                        return body.get("result")
                raise RuntimeError(desc)
            return body.get("result")
        except Exception:
            logger.exception("Review bot sendDocument failed for %s", path)
            return None

    async def edit_message(
        self,
        chat_id: int | str,
        message_id: int,
        text: str,
        *,
        reply_markup: dict | None = None,
        parse_mode: str = "HTML",
    ) -> bool:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        try:
            await self._api("editMessageText", payload)
            return True
        except Exception as exc:
            # Caption-only documents can't use editMessageText
            if "there is no text" in str(exc).lower() or "message is not modified" in str(exc).lower():
                try:
                    cap_payload = {
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "caption": text[:1024],
                        "parse_mode": parse_mode,
                    }
                    if reply_markup is not None:
                        cap_payload["reply_markup"] = reply_markup
                    await self._api("editMessageCaption", cap_payload)
                    return True
                except Exception:
                    logger.exception("Review bot editMessageCaption failed")
                    return False
            logger.exception("Review bot editMessageText failed")
            return False

    async def delete_message(
        self,
        chat_id: int | str,
        message_id: int,
    ) -> bool:
        try:
            await self._api(
                "deleteMessage",
                {"chat_id": chat_id, "message_id": message_id},
            )
            return True
        except Exception:
            logger.debug(
                "Review bot deleteMessage failed (chat=%s msg=%s)",
                chat_id,
                message_id,
                exc_info=True,
            )
            return False

    def schedule_delete_message(
        self,
        chat_id: int | str,
        message_id: int,
        *,
        delay_seconds: float = 300,
    ) -> None:
        """Delete a bot message after delay (default 5 minutes)."""

        async def _delayed_delete() -> None:
            try:
                await asyncio.sleep(delay_seconds)
                ok = await self.delete_message(chat_id, message_id)
                if ok:
                    logger.info(
                        "Deleted timed-out skip notice msg_id=%s after %.0fs",
                        message_id,
                        delay_seconds,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug(
                    "Scheduled delete failed for msg_id=%s",
                    message_id,
                    exc_info=True,
                )

        task = asyncio.create_task(
            _delayed_delete(),
            name=f"review-bot-delete-{message_id}",
        )
        self._delete_tasks.add(task)
        task.add_done_callback(self._delete_tasks.discard)

    async def answer_callback(
        self,
        callback_query_id: str,
        *,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text[:200]
            payload["show_alert"] = show_alert
        try:
            await self._api("answerCallbackQuery", payload)
        except Exception:
            logger.debug("answerCallbackQuery failed", exc_info=True)

    def _chat_allowed(self, chat_id: int | str | None) -> bool:
        """True if this chat is the optional admin receipt chat."""
        if chat_id is None or not self.chat_id:
            return False
        want = self.chat_id.lstrip("-")
        got = str(chat_id).lstrip("-")
        return want == got or want.endswith(got) or got.endswith(want)

    def _is_admin(
        self,
        chat_id: int | str | None = None,
        *,
        telegram_user_id: int | None = None,
    ) -> bool:
        """Admin if telegram user id is in TELEGRAM_ADMIN_IDS (or review chat id)."""
        if telegram_user_id is not None and int(telegram_user_id) in settings.admin_telegram_ids:
            return True
        return self._chat_allowed(chat_id)

    async def _poll_loop(self) -> None:
        logger.info("Review bot long-polling for updates")
        while self._running:
            try:
                updates = await self._api(
                    "getUpdates",
                    {
                        "offset": self._offset,
                        "timeout": 25,
                        "allowed_updates": ["callback_query", "message"],
                    },
                )
                for upd in updates or []:
                    self._offset = max(self._offset, int(upd.get("update_id", 0)) + 1)
                    cq = upd.get("callback_query")
                    if cq:
                        await self._handle_callback(cq)
                        continue
                    msg = upd.get("message")
                    if msg:
                        await self._handle_message(msg)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Review bot poll error")
                await asyncio.sleep(3)

    async def _handle_message(self, msg: dict) -> None:
        from app.billing import bot_admin, bot_plans
        from app.billing.service import get_or_create_user
        from app.database import SessionLocal
        from app.telegram import bot_settings
        from app.telegram.keyboards import main_reply_keyboard

        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            return

        from_user = msg.get("from") or {}
        telegram_user_id = from_user.get("id")
        is_admin = self._is_admin(
            chat_id,
            telegram_user_id=int(telegram_user_id) if telegram_user_id is not None else None,
        )
        uid = int(telegram_user_id) if telegram_user_id is not None else None

        # Register any Telegram user who messages the bot
        if telegram_user_id is not None:
            db = SessionLocal()
            try:
                get_or_create_user(
                    db,
                    telegram_user_id=int(telegram_user_id),
                    chat_id=int(chat_id),
                    username=from_user.get("username"),
                    first_name=from_user.get("first_name"),
                )
            finally:
                db.close()

        # Card-to-card receipt: photo or document from any user with an open order
        photo = msg.get("photo")
        doc = msg.get("document")
        receipt_file_id: str | None = None
        if photo and isinstance(photo, list) and photo:
            # Largest size last
            receipt_file_id = (photo[-1] or {}).get("file_id")
        elif doc:
            mime = (doc.get("mime_type") or "").lower()
            name = (doc.get("file_name") or "").lower()
            if (
                mime.startswith("image/")
                or mime == "application/pdf"
                or name.endswith((".jpg", ".jpeg", ".png", ".webp", ".pdf"))
            ):
                receipt_file_id = doc.get("file_id")

        if receipt_file_id and telegram_user_id is not None:
            # Prefer explicit awaiting-receipt; otherwise attach to open order
            waiting = bot_plans.awaiting_receipt_subscription_id(int(telegram_user_id))
            from app.billing.service import get_pending_subscription, get_user_by_telegram_id

            has_open = waiting is not None
            if not has_open:
                db = SessionLocal()
                try:
                    user = get_user_by_telegram_id(db, int(telegram_user_id))
                    if user and get_pending_subscription(db, user.id):
                        has_open = True
                finally:
                    db.close()
            if has_open:
                result = await bot_plans.handle_receipt_upload(
                    telegram_user_id=int(telegram_user_id),
                    chat_id=int(chat_id),
                    file_id=receipt_file_id,
                    username=from_user.get("username"),
                    first_name=from_user.get("first_name"),
                    subscription_id=waiting,
                )
                if result.get("handled"):
                    if result.get("message"):
                        await self.send_message(
                            result["message"],
                            chat_id=chat_id,
                            reply_markup=main_reply_keyboard(include_admin=is_admin, telegram_user_id=uid),
                        )
                    notify = result.get("notify_admin_receipt")
                    if notify and self.admin_configured:
                        await self.send_photo(
                            notify["file_id"],
                            chat_id=self.chat_id,
                            caption=notify.get("caption") or "Receipt",
                            reply_markup=notify.get("reply_markup"),
                        )
                    return

        # User tools: DOCX upload for AI resume / ATS flows
        if doc and telegram_user_id is not None:
            from app.telegram import bot_user_tools

            if bot_user_tools.pending_for(int(telegram_user_id)):
                try:
                    content = await self._download_telegram_file(doc.get("file_id") or "")
                except Exception as exc:
                    await self.send_message(
                        f"❌ دانلود فایل ممکن نشد: {exc}",
                        chat_id=chat_id,
                    )
                    return
                result = await bot_user_tools.handle_document(
                    telegram_user_id=int(telegram_user_id),
                    filename=doc.get("file_name") or "",
                    content=content,
                )
                if result.get("handled"):
                    await self._apply_user_tool_result(
                        result,
                        chat_id=int(chat_id),
                        is_admin=is_admin,
                        telegram_user_id=uid,
                    )
                    return

        text = (msg.get("text") or "").strip()
        if not text:
            return

        # Normalize "/start@BotName" → "/start" for menu / deep-link commands
        if text.startswith("/") and "@" in text.split()[0]:
            cmd, _, rest = text.partition(" ")
            cmd = cmd.split("@", 1)[0]
            text = f"{cmd} {rest}".strip() if rest else cmd

        from app.telegram import bot_user_tools

        # Cancel / continue user tool flows
        if telegram_user_id is not None and bot_user_tools.pending_for(int(telegram_user_id)):
            result = await bot_user_tools.handle_text(
                telegram_user_id=int(telegram_user_id),
                text=text,
            )
            if result.get("handled"):
                await self._apply_user_tool_result(
                    result,
                    chat_id=int(chat_id),
                    is_admin=is_admin,
                    telegram_user_id=uid,
                )
                return

        # Cancel waiting for card-to-card receipt
        if (
            telegram_user_id is not None
            and bot_plans.awaiting_receipt_subscription_id(int(telegram_user_id))
            and text.lower() in ("cancel", "/cancel", "لغو", "انصراف")
        ):
            bot_plans.clear_awaiting_receipt(int(telegram_user_id))
            await self.send_message(
                "ارسال رسید لغو شد. سفارش شما همچنان باز است — "
                "هر وقت آماده بودید دوباره «پرداخت کردم — ارسال رسید» را بزنید.",
                chat_id=chat_id,
                reply_markup=main_reply_keyboard(include_admin=is_admin, telegram_user_id=uid),
            )
            return

        # Admin commerce field edit (prices / card)
        if is_admin and bot_admin.pending_for(chat_id):
            result = await bot_admin.handle_text_value(chat_id, text)
            if result.get("handled"):
                if result.get("message"):
                    await self.send_message(
                        result["message"],
                        chat_id=chat_id,
                        reply_markup=main_reply_keyboard(include_admin=True),
                    )
                if result.get("follow_up"):
                    await self.send_message(
                        result["follow_up"],
                        chat_id=chat_id,
                        reply_markup=result.get("reply_markup"),
                    )
                return

        # Pending value for a settings edit (admin only)
        if is_admin and bot_settings.pending_for(chat_id):
            result = await bot_settings.handle_text_value(chat_id, text)
            if result.get("handled"):
                if result.get("delete_user_message"):
                    mid = msg.get("message_id")
                    if mid is not None:
                        await self.delete_message(chat_id, int(mid))
                if result.get("message"):
                    await self.send_message(
                        result["message"],
                        chat_id=chat_id,
                        reply_markup=main_reply_keyboard(),
                    )
                if result.get("follow_up"):
                    await self.send_message(
                        result["follow_up"],
                        chat_id=chat_id,
                        reply_markup=result.get("reply_markup"),
                    )
                return

        lower = text.lower().strip()

        if lower in START_LABELS or text in START_LABELS:
            await self._open_start(
                chat_id=int(chat_id),
                telegram_user_id=int(telegram_user_id) if telegram_user_id else None,
                is_admin=is_admin,
                username=from_user.get("username"),
                first_name=from_user.get("first_name"),
            )
            return

        if text in PLANS_BUTTON_LABELS or lower in (
            "plans",
            "plan",
            "/plans",
            "/plan",
        ) or text in ("ساخت حساب کاربری", "📝 ساخت حساب کاربری"):
            await self._open_plans(
                chat_id=int(chat_id),
                telegram_user_id=int(telegram_user_id) if telegram_user_id else 0,
            )
            return

        if text in ACCOUNT_STATUS_LABELS or lower in (
            "status",
            "account",
            "/status",
            "/account",
            "وضعیت",
        ):
            if telegram_user_id is None:
                await self.send_message("شناسه کاربر یافت نشد.", chat_id=chat_id)
                return
            await self._open_account_status(
                chat_id=int(chat_id),
                telegram_user_id=int(telegram_user_id),
            )
            return

        if text in UPGRADE_PLAN_LABELS or lower in ("upgrade", "/upgrade", "ارتقا"):
            if telegram_user_id is None:
                await self.send_message("شناسه کاربر یافت نشد.", chat_id=chat_id)
                return
            await self._open_upgrade(
                chat_id=int(chat_id),
                telegram_user_id=int(telegram_user_id),
            )
            return

        if text in bot_user_tools.AI_RESUME_LABELS or lower in (
            "ai resume",
            "/ai_resume",
            "/resume",
            "resume",
        ):
            if telegram_user_id is None:
                await self.send_message("شناسه کاربر یافت نشد.", chat_id=chat_id)
                return
            result = bot_user_tools.start_ai_resume(int(telegram_user_id))
            await self._apply_user_tool_result(
                result,
                chat_id=int(chat_id),
                is_admin=is_admin,
                telegram_user_id=uid,
            )
            return

        if text in bot_user_tools.APPLY_LABELS or lower in ("/apply", "apply"):
            if telegram_user_id is None:
                await self.send_message("شناسه کاربر یافت نشد.", chat_id=chat_id)
                return
            result = bot_user_tools.start_apply(
                int(telegram_user_id),
                chat_id=int(chat_id),
            )
            await self._apply_user_tool_result(
                result,
                chat_id=int(chat_id),
                is_admin=is_admin,
                telegram_user_id=uid,
            )
            return

        if text in bot_user_tools.PC_WORKER_LABELS or lower in (
            "/worker",
            "worker",
            "pc worker",
        ):
            result = bot_user_tools.pc_worker_status_message()
            await self._apply_user_tool_result(
                result,
                chat_id=int(chat_id),
                is_admin=is_admin,
                telegram_user_id=uid,
            )
            return

        if text in bot_user_tools.ATS_CHECK_LABELS or lower in ("ats", "/ats"):
            if telegram_user_id is None:
                await self.send_message("شناسه کاربر یافت نشد.", chat_id=chat_id)
                return
            result = bot_user_tools.start_ats_check(int(telegram_user_id))
            await self._apply_user_tool_result(
                result,
                chat_id=int(chat_id),
                is_admin=is_admin,
                telegram_user_id=uid,
            )
            return

        if text in bot_user_tools.COMBINED_LABELS or lower in (
            "resume ats",
            "/resume_ats",
            "/combined",
            "رزومه + ats",
        ):
            if telegram_user_id is None:
                await self.send_message("شناسه کاربر یافت نشد.", chat_id=chat_id)
                return
            result = bot_user_tools.start_combined(int(telegram_user_id))
            await self._apply_user_tool_result(
                result,
                chat_id=int(chat_id),
                is_admin=is_admin,
                telegram_user_id=uid,
            )
            return

        if text in ADMIN_SALES_LABELS or lower in ("admin", "/admin", "sales", "/sales", "مدیریت فروش"):
            if not is_admin:
                await self.send_message(
                    "این بخش فقط برای ادمین است.",
                    chat_id=chat_id,
                    reply_markup=main_reply_keyboard(include_admin=False, telegram_user_id=uid),
                )
                return
            await self._open_admin_sales(
                chat_id=int(chat_id),
                telegram_user_id=int(telegram_user_id) if telegram_user_id else None,
            )
            return

        if text in SETTINGS_BUTTON_LABELS or lower in ("settings", "/settings"):
            if not is_admin:
                await self.send_message(
                    "تنظیمات فعلاً فقط برای ادمین است. برای اشتراک از <b>💎 پلن‌ها</b> استفاده کنید.",
                    chat_id=chat_id,
                    reply_markup=main_reply_keyboard(include_admin=False, telegram_user_id=uid),
                )
                return
            await self._open_settings(chat_id=chat_id, refresh_keyboard=True)
            return

        if text in SEARCH_SETUP_LABELS or lower in ("search", "search setup"):
            if not is_admin:
                await self.send_message(
                    "تنظیم جستجو فعلاً فقط برای ادمین است.",
                    chat_id=chat_id,
                    reply_markup=main_reply_keyboard(include_admin=False, telegram_user_id=uid),
                )
                return
            await self._open_settings_category("li", chat_id=chat_id, title="🔍 تنظیم جستجو")
            return

        if text in GMAIL_SETUP_LABELS or lower in ("gmail", "email setup"):
            if not is_admin:
                await self.send_message(
                    "راه‌اندازی جیمیل فعلاً فقط برای ادمین است.",
                    chat_id=chat_id,
                    reply_markup=main_reply_keyboard(include_admin=False, telegram_user_id=uid),
                )
                return
            await self._open_settings_category(
                "li",
                chat_id=chat_id,
                title="📧 جیمیل",
                intro=(
                    "از دکمه‌های <b>📧 آدرس جیمیل</b> و <b>🔑 رمز اپ جیمیل</b> "
                    "استفاده کنید، بعد <b>🔌 تست اتصال جیمیل</b> را بزنید."
                ),
            )
            return

        from app.telegram import lists as bot_lists

        if text in bot_lists.LI_JOBS_LIST_LABELS or lower in (
            "linkedin jobs list",
            "/li_jobs_list",
            "/jobs",
            "jobs",
        ):
            if not is_admin:
                await self.send_message(
                    "لیست شغل‌ها فعلاً فقط برای ادمین است.",
                    chat_id=chat_id,
                    reply_markup=main_reply_keyboard(include_admin=False, telegram_user_id=uid),
                )
                return
            await self._open_pending_list("li", chat_id=chat_id)
            return

        if not is_admin:
            if telegram_user_id is not None and bot_plans.awaiting_receipt_subscription_id(
                int(telegram_user_id)
            ):
                await self.send_message(
                    "هنوز منتظر <b>عکس رسید کارت‌به‌کارت</b> هستم "
                    "(یا دکمه <b>لغو</b> را بزنید).",
                    chat_id=chat_id,
                )
                return
            await self.send_message(
                "از دکمه <b>📋 ارسال آگهی</b> یا منوی ☰ کنار کادر متن "
                "(/plans · /account · /resume · /ats · /apply) استفاده کنید.",
                chat_id=chat_id,
                reply_markup=main_reply_keyboard(include_admin=False, telegram_user_id=uid),
            )
            return

        if text in RESOURCE_WATCH_LABELS or lower in ("resources", "resource watch", "/resources", "/resource"):
            await self._open_resource_watch(chat_id=chat_id)
            return

    async def _open_start(
        self,
        *,
        chat_id: int,
        telegram_user_id: int | None,
        is_admin: bool,
        username: str | None = None,
        first_name: str | None = None,
    ) -> None:
        from app.telegram import keyboards as kb
        from app.telegram.keyboards import main_reply_keyboard

        display = (username or "").strip()
        if display:
            greet_name = f"@{display}"
        else:
            greet_name = (first_name or "").strip() or "دوست عزیز"

        if is_admin:
            text = (
                f"سلام {greet_name}\n"
                "<b>Career Pilot</b> — مسیر پیدا کردن و درخواست شغل\n\n"
                "دکمه پایین: <b>📋 ارسال آگهی</b> — پیست JD → ارزیابی + رزومه\n\n"
                "بقیه از منوی کنار کادر متن (☰):\n"
                "/jobs · /search · /gmail · /account · /plans\n"
                "/resume · /ats · /settings · /resources · /admin"
            )
            await self.send_message(
                text,
                chat_id=chat_id,
                reply_markup=main_reply_keyboard(
                    include_admin=True,
                    telegram_user_id=telegram_user_id,
                ),
            )
            return

        text = (
            f"سلام {greet_name}\n"
            "با این ربات می‌تونی مسیر شغلی‌تو حرفه‌ای‌تر کنی\n"
            "از پیدا کردن صدها شغل تو همه دنیا گرفته تا ساخت رزومه‌های اختصاصی برای هر شغل\n"
            "استفاده از هوش مصنوعی برای بالا بردن سرعت ساخت رزومه و بهبود رزومه متناسب با هر شغل\n"
            "سیستم ATS برای امتیازدهی به هر رزومه و بهبود آن‌ها\n\n"
            "دکمه پایین: <b>📋 ارسال آگهی</b>\n"
            "بقیه از منوی کنار کادر متن: /plans · /account · /resume · /ats · /apply"
        )
        inline = kb._markup([[kb._btn("ساخت حساب کاربری", "pl:home")]])
        await self.send_message(
            text,
            chat_id=chat_id,
            reply_markup=inline,
        )
        await self.send_message(
            "برای ارسال آگهی از دکمه پایین استفاده کنید؛ بقیه از منوی ☰ کنار کادر متن.",
            chat_id=chat_id,
            reply_markup=main_reply_keyboard(
                include_admin=is_admin,
                telegram_user_id=telegram_user_id,
            ),
        )

    async def _open_admin_sales(
        self,
        *,
        chat_id: int,
        telegram_user_id: int | None,
    ) -> None:
        from app.billing import bot_admin

        text, markup = bot_admin.render_admin_home(telegram_user_id=telegram_user_id)
        await self.send_message(text, chat_id=chat_id, reply_markup=markup)

    async def _open_plans(self, *, chat_id: int, telegram_user_id: int) -> None:
        from app.billing import bot_plans

        bot_plans.clear_draft(telegram_user_id)
        text, markup = bot_plans.render_plans_home(telegram_user_id=telegram_user_id)
        await self.send_message(text, chat_id=chat_id, reply_markup=markup)

    async def _open_account_status(self, *, chat_id: int, telegram_user_id: int) -> None:
        from app.billing import bot_plans
        from app.telegram.keyboards import main_reply_keyboard

        is_admin = self._is_admin(chat_id, telegram_user_id=telegram_user_id)
        text, markup = bot_plans.render_account_status(telegram_user_id=telegram_user_id)
        await self.send_message(
            text,
            chat_id=chat_id,
            reply_markup=markup,
        )
        # Refresh persistent bottom keyboard (JD shortcut only)
        await self.send_message(
            "دکمه ارسال آگهی آماده است — بقیه از منوی ☰ کنار کادر متن.",
            chat_id=chat_id,
            reply_markup=main_reply_keyboard(
                include_admin=is_admin,
                telegram_user_id=telegram_user_id,
            ),
        )

    async def _open_upgrade(self, *, chat_id: int, telegram_user_id: int) -> None:
        from app.billing import bot_plans

        result = await bot_plans.handle_callback(
            "pl:up",
            telegram_user_id=telegram_user_id,
            chat_id=chat_id,
        )
        text = (result or {}).get("edit_text")
        markup = (result or {}).get("reply_markup")
        if text:
            await self.send_message(text, chat_id=chat_id, reply_markup=markup)
        else:
            await self.send_message(
                (result or {}).get("toast") or "ارتقای پلن",
                chat_id=chat_id,
            )

    async def _download_telegram_file(self, file_id: str) -> bytes:
        if not file_id:
            raise ValueError("file_id خالی است")
        meta = await self._api("getFile", {"file_id": file_id})
        path = (meta or {}).get("file_path")
        if not path:
            raise ValueError("مسیر فایل تلگرام یافت نشد")
        token = settings.telegram_review_bot_token.strip()
        url = f"{API_BASE}/file/bot{token}/{path}"
        if not self._client:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0))
        resp = await self._client.get(url)
        resp.raise_for_status()
        return resp.content

    async def _apply_user_tool_result(
        self,
        result: dict,
        *,
        chat_id: int,
        is_admin: bool,
        telegram_user_id: int | None = None,
    ) -> None:
        from app.telegram.keyboards import main_reply_keyboard

        if result.get("message"):
            await self.send_message(
                result["message"],
                chat_id=chat_id,
                reply_markup=result.get("reply_markup")
                or main_reply_keyboard(
                    include_admin=is_admin,
                    telegram_user_id=telegram_user_id,
                ),
            )
        then_gen = result.get("then_generate")
        if then_gen:
            from app.telegram import bot_user_tools

            gen_result = await bot_user_tools.run_generate_payload(then_gen)
            await self._apply_user_tool_result(
                gen_result,
                chat_id=chat_id,
                is_admin=is_admin,
                telegram_user_id=telegram_user_id,
            )
            return
        if result.get("follow_up"):
            await self.send_message(
                result["follow_up"],
                chat_id=chat_id,
                reply_markup=result.get("reply_markup"),
            )
        send_doc = result.get("send_document")
        send_docs = list(result.get("send_documents") or [])
        if send_doc:
            send_docs.append(
                {
                    "path": send_doc,
                    "caption": result.get("document_caption") or "",
                }
            )
        for i, item in enumerate(send_docs):
            path = item.get("path") if isinstance(item, dict) else item
            caption = item.get("caption", "") if isinstance(item, dict) else ""
            is_last = i == len(send_docs) - 1
            await self.send_document(
                path,
                chat_id=chat_id,
                caption=caption or "",
                reply_markup=result.get("reply_markup") if is_last else None,
            )
        # Keep improve button visible after the file (legacy ATS improve flow)
        if (
            send_docs
            and result.get("reply_markup")
            and not result.get("follow_up")
            and not result.get("skip_improve_hint")
            and not result.get("message")
        ):
            await self.send_message(
                "اگر امتیاز ATS هنوز پایین است، رزومه را با نکات ATS دوباره بسازید:",
                chat_id=chat_id,
                reply_markup=result.get("reply_markup"),
            )

    async def _open_settings(self, *, chat_id: int | str | None = None, refresh_keyboard: bool = False) -> None:
        from app.telegram import bot_settings
        from app.telegram.keyboards import main_reply_keyboard

        if refresh_keyboard:
            await self.send_message(
                "کیبورد به‌روز شد — مسیر شغل:\n"
                "<b>💼 شغل‌های جدید</b> → <b>🔍 تنظیم جستجو</b> → <b>📧 جیمیل</b>",
                chat_id=chat_id,
                reply_markup=main_reply_keyboard(include_admin=True),
            )
        text, markup = bot_settings.render_home()
        await self.send_message(text, chat_id=chat_id, reply_markup=markup)

    async def _open_settings_category(
        self,
        cat: str,
        *,
        chat_id: int | str | None = None,
        title: str = "",
        intro: str = "",
    ) -> None:
        from app.telegram import bot_settings
        from app.telegram.keyboards import main_reply_keyboard

        text, markup = bot_settings.render_category(cat)
        if title or intro:
            header = f"<b>{title}</b>\n\n" if title else ""
            if intro:
                header += f"{intro}\n\n"
            text = header + text
        await self.send_message(
            text,
            chat_id=chat_id,
            reply_markup=markup or main_reply_keyboard(include_admin=True),
        )

    async def _open_resource_watch(self, *, chat_id: int | str | None = None) -> None:
        from app.system.alerts import build_resource_message
        from app.telegram.keyboards import resource_alert_keyboard

        text, _cpu_over, _ram_over = await build_resource_message(force_full=True)
        await self.send_message(text, chat_id=chat_id, reply_markup=resource_alert_keyboard())

    async def _open_pending_list(self, kind: str, *, chat_id: int | str | None = None) -> None:
        from app.telegram import lists as bot_lists
        from app.telegram.keyboards import main_reply_keyboard

        text, markup = bot_lists.build_linkedin_jobs_list()
        await self.send_message(
            text,
            chat_id=chat_id,
            reply_markup=markup or main_reply_keyboard(include_admin=True),
        )

    async def _handle_callback(self, cq: dict) -> None:
        from app.billing import bot_plans
        from app.telegram.keyboards import cleared_keyboard, main_reply_keyboard
        from app.telegram import review_actions
        from app.telegram import bot_settings

        cq_id = cq.get("id") or ""
        data = (cq.get("data") or "").strip()
        msg = cq.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        message_id = msg.get("message_id")
        from_user = cq.get("from") or {}
        telegram_user_id = from_user.get("id")
        uid = int(telegram_user_id) if telegram_user_id is not None else None
        is_admin = self._is_admin(
            chat_id,
            telegram_user_id=uid,
        )

        if chat_id is None:
            await self.answer_callback(cq_id, text="چت نامشخص")
            return

        if not data:
            await self.answer_callback(cq_id, text="عملیات نامشخص")
            return

        # Plan callbacks — any registered user (or admin activate/reject)
        if data.startswith("pl:"):
            if telegram_user_id is None:
                await self.answer_callback(cq_id, text="کاربر نامشخص", show_alert=True)
                return
            try:
                result = await bot_plans.handle_callback(
                    data,
                    telegram_user_id=int(telegram_user_id),
                    chat_id=int(chat_id),
                    username=from_user.get("username"),
                    first_name=from_user.get("first_name"),
                    is_admin=is_admin,
                )
            except Exception as exc:
                logger.exception("Plan callback failed (%s)", data)
                await self.answer_callback(cq_id, text=f"خطا: {exc}"[:180], show_alert=True)
                return

            toast = (result or {}).get("toast") or "باشه"
            await self.answer_callback(
                cq_id,
                text=toast,
                show_alert=bool((result or {}).get("alert")),
            )
            edit_text = (result or {}).get("edit_text")
            if edit_text and message_id is not None:
                await self.edit_message(
                    chat_id,
                    message_id,
                    edit_text,
                    reply_markup=(result or {}).get("reply_markup"),
                )
            prompt = (result or {}).get("prompt")
            if prompt:
                await self.send_message(prompt, chat_id=chat_id)
            notify_admin = (result or {}).get("notify_admin")
            if notify_admin and self.admin_configured:
                await self.send_message(
                    notify_admin["text"],
                    chat_id=self.chat_id,
                    reply_markup=notify_admin.get("reply_markup"),
                )
            notify_user = (result or {}).get("notify_user")
            if notify_user and notify_user.get("chat_id") and notify_user.get("text"):
                notify_uid = None
                try:
                    # Prefer the subscription owner's telegram id if present in payload
                    notify_uid = notify_user.get("telegram_user_id")
                except Exception:
                    notify_uid = None
                await self.send_message(
                    notify_user["text"],
                    chat_id=notify_user["chat_id"],
                    reply_markup=main_reply_keyboard(
                        include_admin=False,
                        telegram_user_id=int(notify_uid) if notify_uid else None,
                    ),
                )
            return

        # User tools cancel / actions
        if data.startswith("ut:"):
            from app.telegram import bot_user_tools

            if telegram_user_id is None:
                await self.answer_callback(cq_id, text="کاربر نامشخص", show_alert=True)
                return
            try:
                result = await bot_user_tools.handle_tool_callback(
                    data, telegram_user_id=int(telegram_user_id)
                )
            except Exception as exc:
                logger.exception("User tool callback failed (%s)", data)
                await self.answer_callback(cq_id, text=f"خطا: {exc}"[:180], show_alert=True)
                return
            await self.answer_callback(
                cq_id,
                text=(result or {}).get("toast") or "باشه",
                show_alert=bool((result or {}).get("alert")),
            )
            edit_text = (result or {}).get("edit_text")
            if edit_text and message_id is not None:
                await self.edit_message(
                    chat_id,
                    message_id,
                    edit_text,
                    reply_markup=(result or {}).get("reply_markup"),
                )
            # Improve / other actions may send messages + run generation / files
            if (
                (result or {}).get("message")
                or (result or {}).get("then_generate")
                or (result or {}).get("send_document")
                or (result or {}).get("send_documents")
            ):
                await self._apply_user_tool_result(
                    result or {},
                    chat_id=int(chat_id),
                    is_admin=is_admin,
                    telegram_user_id=uid,
                )
            return

        # Admin sales panel
        if data.startswith("adm:"):
            from app.billing import bot_admin

            if not is_admin:
                await self.answer_callback(cq_id, text="فقط ادمین", show_alert=True)
                return
            try:
                result = await bot_admin.handle_callback(
                    data, chat_id=chat_id, is_admin=True
                )
            except Exception as exc:
                logger.exception("Admin callback failed (%s)", data)
                await self.answer_callback(cq_id, text=f"خطا: {exc}"[:180], show_alert=True)
                return
            toast = (result or {}).get("toast") or "باشه"
            await self.answer_callback(
                cq_id,
                text=toast,
                show_alert=bool((result or {}).get("alert")),
            )
            edit_text = (result or {}).get("edit_text")
            if edit_text and message_id is not None:
                await self.edit_message(
                    chat_id,
                    message_id,
                    edit_text,
                    reply_markup=(result or {}).get("reply_markup"),
                )
            prompt = (result or {}).get("prompt")
            if prompt:
                await self.send_message(prompt, chat_id=chat_id)
            return

        # Remaining callbacks stay admin-only for now
        if not is_admin:
            await self.answer_callback(cq_id, text="Unauthorized", show_alert=True)
            return

        # Resource monitor retest
        if data == "sys:retest":
            try:
                from app.system.alerts import retest_resources

                result = await retest_resources()
            except Exception as exc:
                logger.exception("Resource retest failed")
                await self.answer_callback(cq_id, text=f"خطا: {exc}"[:180], show_alert=True)
                return
            toast = (result or {}).get("toast") or "بررسی شد"
            await self.answer_callback(cq_id, text=toast)
            edit_text = (result or {}).get("edit_text")
            if edit_text and message_id is not None:
                await self.edit_message(
                    chat_id,
                    message_id,
                    edit_text,
                    reply_markup=(result or {}).get("reply_markup"),
                )
            return

        # Pending list → open / resend LinkedIn review: ls:l:ID
        if data.startswith("ls:"):
            from app.telegram import lists as bot_lists

            parts = data.split(":")
            if len(parts) != 3 or parts[1] != "l":
                await self.answer_callback(cq_id, text="عملیات نامعتبر")
                return
            try:
                entity_id = int(parts[2])
            except ValueError:
                await self.answer_callback(cq_id, text="شناسه نامعتبر")
                return
            try:
                result = await bot_lists.resend_linkedin_review(entity_id)
            except Exception as exc:
                logger.exception("List resend failed (%s)", data)
                await self.answer_callback(cq_id, text=f"خطا: {exc}"[:180], show_alert=True)
                return
            await self.answer_callback(
                cq_id,
                text=(result or {}).get("toast") or "باشه",
                show_alert=bool((result or {}).get("alert")),
            )
            return

        # Settings callbacks: s:...
        if data.startswith("s:"):
            try:
                result = await bot_settings.handle_callback(data, chat_id)
            except Exception as exc:
                logger.exception("Settings callback failed (%s)", data)
                await self.answer_callback(cq_id, text=f"خطا: {exc}"[:180], show_alert=True)
                return

            toast = (result or {}).get("toast") or "باشه"
            await self.answer_callback(
                cq_id,
                text=toast,
                show_alert=bool((result or {}).get("alert")),
            )
            edit_text = (result or {}).get("edit_text")
            if edit_text and message_id is not None:
                await self.edit_message(
                    chat_id,
                    message_id,
                    edit_text,
                    reply_markup=(result or {}).get("reply_markup"),
                )
            prompt = (result or {}).get("prompt")
            if prompt:
                await self.send_message(prompt, chat_id=chat_id, reply_markup=main_reply_keyboard())
            send_doc = (result or {}).get("send_document")
            if send_doc:
                await self.send_document(
                    send_doc,
                    caption=(result or {}).get("caption") or "",
                )
            return

        if data.count(":") < 2:
            await self.answer_callback(cq_id, text="عملیات نامشخص")
            return

        kind, action, raw_id = data.split(":", 2)
        try:
            entity_id = int(raw_id)
        except ValueError:
            await self.answer_callback(cq_id, text="شناسه نامعتبر")
            return

        try:
            result = await review_actions.dispatch(kind, action, entity_id)
        except Exception as exc:
            logger.exception("Review bot callback failed (%s)", data)
            await self.answer_callback(cq_id, text=f"خطا: {exc}"[:180], show_alert=True)
            return

        toast = (result or {}).get("toast") or "باشه"
        await self.answer_callback(cq_id, text=toast)

        edit_text = (result or {}).get("edit_text")
        if edit_text and message_id is not None:
            await self.edit_message(
                chat_id,
                message_id,
                edit_text,
                reply_markup=cleared_keyboard(),
            )


review_bot = ReviewBot()
