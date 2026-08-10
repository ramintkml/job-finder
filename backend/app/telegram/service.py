import asyncio
import html
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable

from sqlalchemy.orm import Session
from telethon import TelegramClient, events
from telethon.tl.custom.message import Message

from app.config import DATA_DIR, SESSION_PATH, settings
from app.database import AtsResume, LinkedInJob, Project, SessionLocal
from app.telegram.channel_messages import (
    format_bid_failed,
    format_bid_success,
    format_linkedin_ats_resume_caption,
    format_linkedin_email_success,
    format_linkedin_job_draft,
    format_linkedin_job_no_recipient,
    format_linkedin_job_review_request,
    format_review_approved,
    format_review_declined,
    format_review_request,
)

logger = logging.getLogger(__name__)

POST_BID_LABELS = ("post bid", "Post bid", "POST BID")
YES_LABELS = ("yes", "Yes", "YES")
CHANNEL_IDS_PATH = DATA_DIR / "telegram_channels.json"

PROPOSAL_PROMPT_MARKERS = (
    "bid description",
    "send me the bid",
    "send your bid",
    "send the bid",
    "proposal for project",
)
AMOUNT_PROMPT_MARKERS = (
    "amount of money",
    "amount to bid",
    "send me the amount",
    "project currency",
    "bid amount",
    "how much",
    "enter the amount",
    "maximum bid",
    "your bid amount",
)
DURATION_PROMPT_MARKERS = (
    "amount of time",
    "time (in days)",
    "in days) it will take",
    "take to complete the project",
    "days to complete",
    "how many days",
    "delivery time",
    "time to complete",
    "how long",
)


class _BotMsgRef:
    """Adapter so Bot API send results look like Telethon Message (id / chat_id)."""

    def __init__(self, result: dict):
        self.id = int(result["message_id"])
        chat = result.get("chat") or {}
        self.chat_id = chat.get("id")


class BidStep(str, Enum):
    IDLE = "idle"
    AWAITING_PROPOSAL_PROMPT = "awaiting_proposal_prompt"
    AWAITING_AMOUNT_PROMPT = "awaiting_amount_prompt"
    AWAITING_DURATION_PROMPT = "awaiting_duration_prompt"
    AWAITING_CONFIRM = "awaiting_confirm"
    AWAITING_RESULT = "awaiting_result"


class TelegramService:
    def __init__(self) -> None:
        self.client: TelegramClient | None = None
        self.running = False
        self.connected = False
        self.needs_auth = False
        self.auth_phone_code_hash: str | None = None
        self.step = BidStep.IDLE
        self.active_project_db_id: int | None = None
        self.active_freelancer_id: str | None = None
        self.pending_proposal: str | None = None
        self.pending_amount: float | None = None
        self.pending_duration: int | None = None
        self._bid_queue: asyncio.Queue[int] = asyncio.Queue()
        self._processor_task: asyncio.Task | None = None
        self._on_update: Callable[[], None] | None = None
        self._bid_lock = asyncio.Lock()
        self._bid_flow_task: asyncio.Task | None = None
        self._channel_handler_registered = False
        self._channel_handler_chat_ids: list[int] = []
        self._channel_entities: dict[str, object] = {}
        self._channel_flood_until: dict[str, float] = {}
        self._persisted_channel_ids: dict[str, int] = self._load_persisted_channel_ids()
        self._result_after_message_id: int | None = None
        self.automation_enabled = True

    def _channel_enabled(self, kind: str = "default") -> bool:
        # Review bot replaces all three legacy channels when configured.
        if self.uses_review_bot():
            return True
        if kind == "freelancer":
            return bool(settings.telegram_freelancer_channel_id.strip())
        if kind == "linkedin":
            return bool(settings.telegram_linkedin_channel_id.strip())
        return bool(settings.telegram_channel_id.strip())

    def _channel_setting(self, kind: str) -> str:
        if kind == "freelancer":
            return settings.telegram_freelancer_channel_id.strip()
        if kind == "linkedin":
            return settings.telegram_linkedin_channel_id.strip()
        return settings.telegram_channel_id.strip()

    def _channel_kind_for_project(self, project: Project) -> str:
        from app.services.project_service import SOURCE_FREELANCER_API

        if (project.source or "") == SOURCE_FREELANCER_API:
            return "freelancer"
        return "default"

    @staticmethod
    def _parse_channel_invite_hash(value: str) -> str | None:
        match = re.search(r"(?:t\.me/\+|\+)([A-Za-z0-9_-]+)", value.strip())
        return match.group(1) if match else None

    @staticmethod
    def _load_persisted_channel_ids() -> dict[str, int]:
        try:
            if CHANNEL_IDS_PATH.exists():
                data = json.loads(CHANNEL_IDS_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {str(k): int(v) for k, v in data.items()}
        except Exception:
            logger.warning("Could not load persisted Telegram channel IDs", exc_info=True)
        return {}

    def _persist_channel_id(self, kind: str, channel_id: int) -> None:
        self._persisted_channel_ids[kind] = channel_id
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            CHANNEL_IDS_PATH.write_text(
                json.dumps(self._persisted_channel_ids, indent=2),
                encoding="utf-8",
            )
        except Exception:
            logger.warning("Could not persist Telegram channel ID for %s", kind, exc_info=True)

    def _channel_flood_blocked(self, kind: str) -> bool:
        until = self._channel_flood_until.get(kind, 0)
        if until and time.time() < until:
            return True
        if until:
            self._channel_flood_until.pop(kind, None)
        return False

    def _record_channel_flood(self, kind: str, seconds: int) -> None:
        self._channel_flood_until[kind] = time.time() + max(seconds, 1)
        logger.warning(
            "Telegram rate-limited %s channel lookup for %s s — using cached IDs if available",
            kind,
            seconds,
        )

    def _telegram_ready(self) -> bool:
        return bool(self.connected and self.client and self.client.is_connected())

    async def _get_channel_entity(self, kind: str = "default"):
        if not self.client or not self._channel_enabled(kind):
            return None
        cached = self._channel_entities.get(kind)
        if cached is not None:
            return cached
        # Poll / timeout loops start before Telethon finishes connecting — skip RPC until ready.
        if not self._telegram_ready():
            return None
        if self._channel_flood_blocked(kind):
            persisted_id = self._persisted_channel_ids.get(kind)
            if persisted_id:
                try:
                    entity = await self.client.get_entity(persisted_id)
                    self._channel_entities[kind] = entity
                    return entity
                except Exception:
                    logger.debug("Persisted %s channel id %s unavailable during flood wait", kind, persisted_id)
            return None

        persisted_id = self._persisted_channel_ids.get(kind)
        if persisted_id:
            try:
                entity = await self.client.get_entity(persisted_id)
                self._channel_entities[kind] = entity
                logger.info("Resolved %s channel from persisted id=%s", kind, persisted_id)
                return entity
            except ConnectionError:
                logger.debug("Telegram not ready — deferred %s channel resolve via persisted id", kind)
                return None
            except Exception:
                logger.debug("Persisted %s channel id %s no longer valid", kind, persisted_id)

        raw = self._channel_setting(kind)
        invite_hash = self._parse_channel_invite_hash(raw)

        if invite_hash:
            from telethon.errors import FloodWaitError, UserAlreadyParticipantError
            from telethon.tl.functions.messages import CheckChatInviteRequest, ImportChatInviteRequest

            try:
                invite = await self.client(CheckChatInviteRequest(invite_hash))
                channel = getattr(invite, "chat", None)
                if channel is None and getattr(invite, "channel", None) is not None:
                    channel = invite.channel
                if channel is None:
                    try:
                        updates = await self.client(ImportChatInviteRequest(invite_hash))
                        channel = updates.chats[0] if updates.chats else None
                    except UserAlreadyParticipantError:
                        invite = await self.client(CheckChatInviteRequest(invite_hash))
                        channel = getattr(invite, "chat", None) or getattr(invite, "channel", None)
                if channel:
                    self._channel_entities[kind] = channel
                    self._persist_channel_id(kind, channel.id)
                    logger.info("Resolved %s channel from invite (id=%s)", kind, channel.id)
                    return channel
            except FloodWaitError as exc:
                self._record_channel_flood(kind, int(exc.seconds))
                return None
            except ConnectionError:
                logger.debug("Telegram not ready — deferred %s channel invite resolve", kind)
                return None
            except Exception:
                logger.exception("Failed to resolve %s channel from invite link", kind)
                return None

        try:
            entity = await self.client.get_entity(raw)
            self._channel_entities[kind] = entity
            self._persist_channel_id(kind, entity.id)
            logger.info("Resolved %s channel %s (id=%s)", kind, raw, entity.id)
            return entity
        except ConnectionError:
            logger.debug("Telegram not ready — deferred %s channel resolve for %s", kind, raw)
            return None
        except Exception:
            logger.exception("Failed to resolve %s channel %s", kind, raw)
            return None

    def _bootstrap_persisted_channel_ids(self) -> None:
        """Seed cached channel IDs from recent notifications when invite links are rate-limited."""
        from app.services.project_service import SOURCE_FREELANCER_API

        db = SessionLocal()
        try:
            if self._channel_enabled("freelancer") and "freelancer" not in self._persisted_channel_ids:
                row = (
                    db.query(Project.review_channel_chat_id)
                    .filter(
                        Project.source == SOURCE_FREELANCER_API,
                        Project.review_channel_chat_id.isnot(None),
                    )
                    .order_by(Project.id.desc())
                    .first()
                )
                if row and row[0]:
                    self._persist_channel_id("freelancer", self._normalize_chat_id(row[0]))

            if self._channel_enabled("linkedin") and "linkedin" not in self._persisted_channel_ids:
                row = (
                    db.query(LinkedInJob.review_channel_chat_id)
                    .filter(LinkedInJob.review_channel_chat_id.isnot(None))
                    .order_by(LinkedInJob.review_notified_at.desc())
                    .first()
                )
                if row and row[0]:
                    self._persist_channel_id("linkedin", self._normalize_chat_id(row[0]))

            if self._channel_enabled("default") and "default" not in self._persisted_channel_ids:
                row = (
                    db.query(Project.review_channel_chat_id)
                    .filter(
                        Project.source != SOURCE_FREELANCER_API,
                        Project.review_channel_chat_id.isnot(None),
                    )
                    .order_by(Project.id.desc())
                    .first()
                )
                if row and row[0]:
                    self._persist_channel_id("default", self._normalize_chat_id(row[0]))
        finally:
            db.close()

    async def _resolve_channel(self, kind: str = "default") -> int | None:
        entity = await self._get_channel_entity(kind)
        return entity.id if entity is not None else None

    async def _channel_target(self, kind: str = "default") -> int | None:
        return await self._resolve_channel(kind)

    async def _mark_channel_unread(self, entity) -> None:
        if not self.client or entity is None:
            return
        try:
            from telethon.tl.functions.messages import MarkDialogUnreadRequest
            from telethon.tl.types import InputDialogPeer

            input_peer = await self.client.get_input_entity(entity)
            await self.client(
                MarkDialogUnreadRequest(
                    peer=InputDialogPeer(peer=input_peer),
                    unread=True,
                )
            )
        except Exception:
            logger.warning("Could not mark channel as unread", exc_info=True)

    async def _send_channel_message(
        self,
        text: str,
        reply_to: int | None = None,
        *,
        channel_kind: str | None = None,
        project: Project | None = None,
        chat_id: int | None = None,
        mark_unread: bool = True,
        parse_mode: str | None = None,
    ) -> Message | None:
        if not self.client:
            return None
        kind = channel_kind or (self._channel_kind_for_project(project) if project else "default")
        if chat_id is not None:
            try:
                entity = await self.client.get_entity(chat_id)
            except Exception:
                logger.exception("Could not resolve chat_id %s", chat_id)
                return None
        else:
            if not self._channel_enabled(kind):
                logger.warning("Channel message skipped — %s channel not configured", kind)
                return None
            entity = await self._get_channel_entity(kind)
            if not entity:
                if not self._telegram_ready():
                    logger.debug("Channel message deferred — Telegram not connected yet (%s)", kind)
                else:
                    logger.error("Channel message skipped — could not resolve %s channel", kind)
                return None
        try:
            msg = await self.client.send_message(
                entity,
                text,
                reply_to=reply_to,
                parse_mode=parse_mode,
            )
            if mark_unread and msg:
                await self._mark_channel_unread(entity)
            await self._register_channel_handler()
            return msg
        except Exception:
            if parse_mode:
                try:
                    msg = await self.client.send_message(entity, text, reply_to=reply_to)
                    if mark_unread and msg:
                        await self._mark_channel_unread(entity)
                    await self._register_channel_handler()
                    return msg
                except Exception:
                    logger.exception("Failed to send channel message (plain fallback) to %s channel", kind)
                    return None
            logger.exception("Failed to send channel message to %s channel", kind)
            return None

    async def _notify_bid_success(self, project_db_id: int) -> None:
        db = SessionLocal()
        try:
            project = db.get(Project, project_db_id)
            if not project:
                return
            text = format_bid_success(project, for_bot=self.uses_review_bot())
            if self.uses_review_bot():
                from app.telegram.bot import review_bot

                await review_bot.send_message(text, parse_mode="HTML")
            else:
                await self._send_channel_message(text, project=project)
        finally:
            db.close()

    async def _notify_bid_failed(self, project_db_id: int, reason: str, stage: str = "Bidding") -> None:
        db = SessionLocal()
        try:
            project = db.get(Project, project_db_id)
            if not project:
                return
            text = format_bid_failed(project, reason, stage=stage)
            if self.uses_review_bot():
                from app.telegram.bot import review_bot

                msg = await review_bot.send_message(text, parse_mode=None)
                ok = bool(msg)
            else:
                msg = await self._send_channel_message(text, project=project)
                ok = bool(msg)
            if ok:
                logger.info("Sent %s notification for project %s", stage, project_db_id)
            else:
                logger.warning("Notification not sent for project %s (%s)", project_db_id, stage)
        finally:
            db.close()

    async def notify_project_failed(
        self, project_db_id: int, reason: str, stage: str = "Bidding"
    ) -> None:
        await self._dispatch_channel_notification(
            self._notify_bid_failed(project_db_id, reason, stage=stage)
        )

    async def _dispatch_channel_notification(self, coro) -> None:
        try:
            await coro
        except Exception:
            logger.exception("Channel notification failed")

    @staticmethod
    def uses_review_bot() -> bool:
        from app.telegram.bot import review_bot

        return review_bot.configured

    def _review_target_ready(self, kind: str = "default") -> bool:
        """True if we can deliver a review notification (bot preferred, else channel)."""
        if self.uses_review_bot():
            return True
        return self._channel_enabled(kind)

    async def _record_review_notification(
        self,
        db: Session,
        project: Project,
        msg,
        *,
        kind: str,
    ) -> None:
        channel_chat_id = getattr(msg, "chat_id", None)
        if channel_chat_id is None and not self.uses_review_bot():
            channel_chat_id = await self._resolve_channel(kind)
        project.review_channel_message_id = msg.id
        project.review_channel_chat_id = channel_chat_id
        project.review_notified_at = datetime.now(timezone.utc)
        db.commit()

    async def notify_review_request(
        self,
        project_db_id: int,
        *,
        force: bool = False,
        resend: bool = False,
    ) -> bool:
        if not force and not self.intake_allowed():
            logger.info(
                "Review notify skipped for project %s — automation is paused",
                project_db_id,
            )
            return False

        db = SessionLocal()
        try:
            project = db.get(Project, project_db_id)
            if not project:
                logger.warning("Review notify: project %s not found", project_db_id)
                return False
            db.refresh(project)
            if project.status != "pending_review":
                logger.warning(
                    "Review notify skipped for project %s — status=%s (expected pending_review)",
                    project_db_id,
                    project.status,
                )
                return False
            if project.review_channel_message_id and project.review_notified_at and not resend:
                logger.info(
                    "Review notify skipped for project %s — already sent (msg_id=%s)",
                    project_db_id,
                    project.review_channel_message_id,
                )
                return True
            kind = self._channel_kind_for_project(project)
            if not self._review_target_ready(kind):
                logger.error(
                    "Review notification not sent for project %s — configure review bot "
                    "(TELEGRAM_REVIEW_BOT_TOKEN + CHAT_ID) or TELEGRAM_%sCHANNEL_ID",
                    project_db_id,
                    "FREELANCER_" if kind == "freelancer" else "",
                )
                return False

            if self.uses_review_bot():
                from app.telegram.bot import review_bot
                from app.telegram.keyboards import project_review_keyboard
                from app.services.project_service import SOURCE_FREELANCER_API

                is_api = (project.source or "") == SOURCE_FREELANCER_API
                result = await review_bot.send_message(
                    format_review_request(project, for_bot=True),
                    reply_markup=project_review_keyboard(project.id, api_source=is_api),
                )
                if result:
                    msg = _BotMsgRef(result)
                    await self._record_review_notification(db, project, msg, kind=kind)
                    logger.info(
                        "Sent review notification for project %s via review bot (msg_id=%s)",
                        project_db_id,
                        msg.id,
                    )
                    return True
                logger.error("Review bot failed to notify project %s", project_db_id)
                return False

            msg = await self._send_channel_message(
                format_review_request(project),
                project=project,
                channel_kind=kind,
                parse_mode="html",
            )
            if msg:
                await self._record_review_notification(db, project, msg, kind=kind)
                logger.info(
                    "Sent review notification for project %s to %s channel (msg_id=%s)",
                    project_db_id,
                    kind,
                    msg.id,
                )
                return True
            logger.error(
                "Review notification not sent for project %s — check TELEGRAM_%sCHANNEL_ID",
                project_db_id,
                "FREELANCER_" if kind == "freelancer" else "",
            )
            return False
        finally:
            db.close()

    async def _notify_review_request(self, project_db_id: int) -> None:
        await self.notify_review_request(project_db_id)

    async def renotify_pending_freelancer_projects(self) -> int:
        from app.services.project_service import SOURCE_FREELANCER_API

        if not self.intake_allowed():
            logger.info("Renotify skipped — automation is paused")
            return 0

        db = SessionLocal()
        sent = 0
        try:
            pending = (
                db.query(Project)
                .filter(
                    Project.source == SOURCE_FREELANCER_API,
                    Project.status == "pending_review",
                    Project.review_channel_message_id.is_(None),
                )
                .all()
            )
            for project in pending:
                await self.notify_review_request(project.id)
                db.refresh(project)
                if project.review_channel_message_id:
                    sent += 1
        finally:
            db.close()
        return sent

    async def expire_stale_review_requests(self) -> int:
        """Auto-decline pending_review Freelancer projects with no reply in time."""
        from app.services.project_service import skip_project_review

        timeout = timedelta(minutes=settings.review_timeout_minutes)
        cutoff = (datetime.now(timezone.utc) - timeout).replace(tzinfo=None)
        declined = 0

        db = SessionLocal()
        try:
            pending = (
                db.query(Project)
                .filter(
                    Project.status == "pending_review",
                    Project.review_channel_message_id.isnot(None),
                    Project.review_notified_at.isnot(None),
                    Project.review_notified_at <= cutoff,
                )
                .all()
            )
            for project in pending:
                skip_project_review(
                    db,
                    project,
                    f"Auto-declined — no reply within {settings.review_timeout_minutes} minutes",
                )
                declined += 1
                try:
                    if self.uses_review_bot():
                        # No decline spam to the review bot — quietly clear the review message.
                        from app.telegram.bot import review_bot
                        from app.telegram.keyboards import cleared_keyboard

                        msg_id = project.review_channel_message_id
                        code = html.escape(
                            str(project.freelancer_project_id or project.id)
                        )
                        if msg_id:
                            await review_bot.edit_message(
                                review_bot.chat_id,
                                int(msg_id),
                                f"⏭ Timed out — skipped <code>{code}</code>.",
                                reply_markup=cleared_keyboard(),
                                parse_mode="HTML",
                            )
                            # Remove the notice from the chat after 5 minutes
                            review_bot.schedule_delete_message(
                                review_bot.chat_id,
                                int(msg_id),
                                delay_seconds=5 * 60,
                            )
                    else:
                        text = format_review_declined(
                            project,
                            auto=True,
                            timeout_minutes=settings.review_timeout_minutes,
                        )
                        await self._send_channel_message(text, project=project)
                except Exception:
                    logger.exception("Failed to clear auto-decline notice for project %s", project.id)
                logger.info(
                    "Auto-declined project %s (%s) after %s min without review reply",
                    project.id,
                    project.source or "telegram_bot",
                    settings.review_timeout_minutes,
                )

            # Never notified (channel misconfigured) — expire by updated_at / created_at
            orphan_pending = (
                db.query(Project)
                .filter(
                    Project.status == "pending_review",
                    Project.review_notified_at.is_(None),
                )
                .all()
            )
            for project in orphan_pending:
                anchor = project.updated_at or project.created_at
                if not anchor:
                    continue
                anchor_naive = anchor.replace(tzinfo=None) if getattr(anchor, "tzinfo", None) else anchor
                if anchor_naive > cutoff:
                    continue
                skip_project_review(
                    db,
                    project,
                    f"Auto-declined — review never reached Telegram within {settings.review_timeout_minutes} minutes",
                )
                declined += 1
                logger.warning(
                    "Auto-declined project %s — pending_review with no channel notification",
                    project.id,
                )
        finally:
            db.close()

        if declined:
            self._notify()
        return declined

    async def notify_linkedin_email_sent(self, job) -> None:
        """Post sent LinkedIn application details to the review bot / LinkedIn channel."""
        if self.uses_review_bot():
            from app.telegram.bot import review_bot

            await review_bot.send_message(format_linkedin_email_success(job), parse_mode=None)
            return
        if not self.connected or not self._channel_enabled("linkedin"):
            return
        msg = await self._send_channel_message(
            format_linkedin_email_success(job),
            channel_kind="linkedin",
        )
        if msg:
            logger.info("LinkedIn channel notification sent for job %s", getattr(job, "id", "?"))
        else:
            logger.warning("LinkedIn channel notification not sent for job %s", getattr(job, "id", "?"))

    async def notify_linkedin_job_no_recipient(self, job) -> None:
        """Post composed draft when no hiring email exists (legacy auto-mail path)."""
        await self.notify_linkedin_job_draft(job)

    async def notify_linkedin_job_draft(self, job) -> None:
        """Post AI-composed application email draft to the review bot / LinkedIn channel."""
        if self.uses_review_bot():
            from app.telegram.bot import review_bot

            result = await review_bot.send_message(
                format_linkedin_job_draft(job),
                parse_mode="HTML",
            )
            if result:
                logger.info("LinkedIn draft sent via review bot for job %s", getattr(job, "id", "?"))
            else:
                logger.warning("LinkedIn draft not sent via review bot for job %s", getattr(job, "id", "?"))
            return
        if not self.connected or not self._channel_enabled("linkedin"):
            return
        msg = await self._send_channel_message(
            format_linkedin_job_draft(job),
            channel_kind="linkedin",
            parse_mode="html",
        )
        if msg:
            logger.info("LinkedIn draft channel notification sent for job %s", getattr(job, "id", "?"))
        else:
            logger.warning("LinkedIn draft channel notification not sent for job %s", getattr(job, "id", "?"))

    async def notify_linkedin_ats_resume(self, ats_resume_id: int) -> bool:
        """Post tailored ATS resume files to the review bot / LinkedIn channel."""
        from pathlib import Path

        if self.uses_review_bot():
            from app.telegram.bot import review_bot
            from app.telegram.keyboards import ats_resume_keyboard

            db = SessionLocal()
            try:
                row = db.get(AtsResume, ats_resume_id)
                if not row or row.status != "ready":
                    return False
                job = db.get(LinkedInJob, row.linkedin_job_db_id)
                if not job:
                    return False
                band = None
                if row.scores_json:
                    try:
                        band = json.loads(row.scores_json).get("band")
                    except json.JSONDecodeError:
                        band = None
                caption = format_linkedin_ats_resume_caption(
                    job,
                    total_score=row.total_score,
                    band=band,
                    for_bot=True,
                )
                files: list[str] = []
                if row.docx_path and Path(row.docx_path).exists():
                    files.append(row.docx_path)
                if row.pdf_path and Path(row.pdf_path).exists():
                    files.append(row.pdf_path)
                if not files:
                    logger.error("ATS resume %s has no files to send", ats_resume_id)
                    return False
                first = None
                for i, fpath in enumerate(files):
                    result = await review_bot.send_document(
                        fpath,
                        caption=caption if i == 0 else "",
                        reply_markup=ats_resume_keyboard(row.id) if i == 0 else None,
                    )
                    if result and first is None:
                        first = _BotMsgRef(result)
                if first:
                    row.channel_message_id = first.id
                    row.channel_chat_id = first.chat_id
                    db.commit()
                    logger.info(
                        "ATS resume sent via review bot for job %s (msg_id=%s)",
                        job.id,
                        first.id,
                    )
                    return True
                return False
            except Exception:
                logger.exception("Failed to send ATS resume %s via review bot", ats_resume_id)
                return False
            finally:
                db.close()

        if not self._telegram_ready() or not self._channel_enabled("linkedin"):
            logger.warning("ATS resume notify skipped — Telegram/channel not ready")
            return False

        db = SessionLocal()
        try:
            row = db.get(AtsResume, ats_resume_id)
            if not row or row.status != "ready":
                return False
            job = db.get(LinkedInJob, row.linkedin_job_db_id)
            if not job:
                return False

            entity = await self._get_channel_entity("linkedin")
            if not entity:
                return False

            band = None
            if row.scores_json:
                try:
                    band = json.loads(row.scores_json).get("band")
                except json.JSONDecodeError:
                    band = None
            caption = format_linkedin_ats_resume_caption(
                job,
                total_score=row.total_score,
                band=band,
            )
            files: list[str] = []
            if row.docx_path and Path(row.docx_path).exists():
                files.append(row.docx_path)
            if row.pdf_path and Path(row.pdf_path).exists():
                files.append(row.pdf_path)
            if not files:
                logger.error("ATS resume %s has no files to send", ats_resume_id)
                return False

            msg = None
            if len(files) == 1:
                msg = await self.client.send_file(
                    entity,
                    files[0],
                    caption=caption,
                    parse_mode="html",
                    force_document=True,
                )
            else:
                msg = await self.client.send_file(
                    entity,
                    files,
                    caption=caption,
                    parse_mode="html",
                    force_document=True,
                )
            if msg:
                first = msg[0] if isinstance(msg, list) else msg
                row.channel_message_id = first.id
                row.channel_chat_id = getattr(first, "chat_id", None) or await self._resolve_channel("linkedin")
                db.commit()
                await self._mark_channel_unread(entity)
                logger.info("ATS resume channel message sent for job %s (msg_id=%s)", job.id, first.id)
                return True
            return False
        except Exception:
            logger.exception("Failed to send ATS resume %s to channel", ats_resume_id)
            return False
        finally:
            db.close()

    async def _record_linkedin_review_notification(
        self,
        db: Session,
        job: LinkedInJob,
        msg,
    ) -> None:
        channel_chat_id = getattr(msg, "chat_id", None)
        if channel_chat_id is None and not self.uses_review_bot():
            channel_chat_id = await self._resolve_channel("linkedin")
        job.review_channel_message_id = msg.id
        job.review_channel_chat_id = channel_chat_id
        job.review_notified_at = datetime.now(timezone.utc)
        db.commit()

    async def notify_linkedin_job_review(
        self,
        job_db_id: int,
        *,
        force: bool = False,
        resend: bool = False,
    ) -> bool:
        """Post a newly matched LinkedIn job for create/resume/skip review."""
        if not force and not self.intake_allowed():
            logger.info("LinkedIn review notify skipped for job %s — automation paused", job_db_id)
            return False
        if not self._review_target_ready("linkedin"):
            logger.warning(
                "LinkedIn review notify skipped for job %s — configure review bot or TELEGRAM_LINKEDIN_CHANNEL_ID",
                job_db_id,
            )
            return False
        if not self.uses_review_bot() and (not self.connected or not self.client):
            logger.warning(
                "LinkedIn review notify skipped for job %s — Telegram not connected (log in via Settings)",
                job_db_id,
            )
            return False

        db = SessionLocal()
        try:
            job = db.get(LinkedInJob, job_db_id)
            if not job:
                return False
            if job.status != "matched":
                return False
            if job.review_channel_message_id and job.review_notified_at and not resend:
                return True

            if self.uses_review_bot():
                from app.telegram.bot import review_bot
                from app.telegram.keyboards import linkedin_job_keyboard

                result = await review_bot.send_message(
                    format_linkedin_job_review_request(job, for_bot=True),
                    reply_markup=linkedin_job_keyboard(job.id, job.job_url),
                )
                if result:
                    msg = _BotMsgRef(result)
                    await self._record_linkedin_review_notification(db, job, msg)
                    logger.info(
                        "LinkedIn review notification sent via bot for job %s (msg_id=%s)",
                        job_db_id,
                        msg.id,
                    )
                    return True
                logger.error("LinkedIn review bot notification NOT sent for job %s", job_db_id)
                return False

            msg = await self._send_channel_message(
                format_linkedin_job_review_request(job),
                channel_kind="linkedin",
                parse_mode="html",
            )
            if msg:
                await self._record_linkedin_review_notification(db, job, msg)
                logger.info("LinkedIn review notification sent for job %s (msg_id=%s)", job_db_id, msg.id)
                return True
            logger.error(
                "LinkedIn review notification NOT sent for job %s — check Telegram login and channel access",
                job_db_id,
            )
            return False
        finally:
            db.close()

    async def renotify_pending_linkedin_jobs(
        self,
        *,
        force: bool = True,
        resend_all: bool = False,
    ) -> dict:
        """Post Job Found messages for matched jobs that never reached the channel."""
        db = SessionLocal()
        try:
            query = db.query(LinkedInJob.id).filter(LinkedInJob.status == "matched")
            if not resend_all:
                query = query.filter(LinkedInJob.review_channel_message_id.is_(None))
            pending_ids = [
                row[0]
                for row in query.order_by(LinkedInJob.created_at.asc()).all()
            ]
        finally:
            db.close()

        pending = len(pending_ids)
        if pending == 0:
            return {"sent": 0, "pending": 0, "failed": 0, "resend_all": resend_all}

        if not self.uses_review_bot() and (not self.connected or not self.client):
            return {
                "sent": 0,
                "pending": pending,
                "failed": pending,
                "error": "Telegram not connected — log in via Settings first.",
            }
        if not self._review_target_ready("linkedin"):
            return {
                "sent": 0,
                "pending": pending,
                "failed": pending,
                "error": "Configure TELEGRAM_REVIEW_BOT_TOKEN + CHAT_ID (or TELEGRAM_LINKEDIN_CHANNEL_ID).",
            }

        sent = 0
        failed = 0
        for job_id in pending_ids:
            if await self.notify_linkedin_job_review(job_id, force=force, resend=resend_all):
                sent += 1
            else:
                failed += 1

        if sent:
            action = "Re-sent" if resend_all else "Sent"
            logger.info("%s %s LinkedIn Job Found notification(s) to channel", action, sent)
        return {"sent": sent, "pending": pending, "failed": failed, "resend_all": resend_all}

    async def test_linkedin_channel_notifications(self) -> dict:
        if self.uses_review_bot():
            from app.telegram.bot import review_bot
            from app.telegram.keyboards import linkedin_job_keyboard

            msg = await review_bot.send_message(
                "🧪 <b>LINKEDIN — REVIEW BOT TEST</b>\n"
                "Matched jobs and ATS resumes are posted here with inline buttons.",
                reply_markup=linkedin_job_keyboard(0, None),
            )
            return {
                "ok": bool(msg),
                "message": "Check your review bot chat for the test message.",
            }
        if not self.connected:
            return {"ok": False, "error": "Telegram not connected."}
        if not self._channel_enabled("linkedin"):
            return {
                "ok": False,
                "error": "Configure TELEGRAM_REVIEW_BOT_TOKEN + CHAT_ID (preferred), or TELEGRAM_LINKEDIN_CHANNEL_ID.",
            }
        entity = await self._get_channel_entity("linkedin")
        if not entity:
            return {"ok": False, "error": "Could not resolve LinkedIn channel."}
        msg = await self._send_channel_message(
            "🧪 LINKEDIN JOBS — CHANNEL TEST\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Successful LinkedIn application emails and job review messages (reply create) are posted here for review.",
            channel_kind="linkedin",
        )
        return {
            "ok": bool(msg),
            "channel_id": entity.id,
            "message": "Check your LinkedIn channel for the test message.",
        }

    async def test_freelancer_channel_notifications(self) -> dict:
        if self.uses_review_bot():
            from app.telegram.bot import review_bot
            from app.telegram.keyboards import project_review_keyboard

            msg = await review_bot.send_message(
                "🧪 <b>FREELANCER — REVIEW BOT TEST</b>\n"
                "API and @KayaProjectsBot matches are posted here with Send bid / Skip buttons.",
                reply_markup=project_review_keyboard(0, api_source=True),
            )
            return {
                "ok": bool(msg),
                "message": "Check your review bot chat for the test message.",
            }
        if not self.connected:
            return {"ok": False, "error": "Telegram not connected."}
        if not self._channel_enabled("freelancer"):
            return {
                "ok": False,
                "error": "Configure TELEGRAM_REVIEW_BOT_TOKEN + CHAT_ID (preferred), or TELEGRAM_FREELANCER_CHANNEL_ID.",
            }
        entity = await self._get_channel_entity("freelancer")
        if not entity:
            return {"ok": False, "error": "Could not resolve Freelancer channel."}
        msg = await self._send_channel_message(
            "🧪 FREELANCER.COM PROJECTS — CHANNEL TEST\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Freelancer API BID READY messages are sent here.\n"
            "Reply send to a BID READY message to post a bid.",
            channel_kind="freelancer",
        )
        return {
            "ok": bool(msg),
            "channel_id": entity.id,
            "message": "Check your Freelancer bid check channel for the test message.",
        }

    @staticmethod
    def _normalize_chat_id(chat_id: int | None) -> int | None:
        """Normalize Telegram channel/supergroup IDs for comparison."""
        if chat_id is None:
            return None
        cid = int(chat_id)
        if cid < 0:
            digits = str(abs(cid))
            if digits.startswith("100") and len(digits) > 3:
                return int(digits[3:])
            return abs(cid)
        return cid

    @classmethod
    def _chat_ids_match(cls, a: int | None, b: int | None) -> bool:
        if a is None or b is None:
            return True
        return cls._normalize_chat_id(a) == cls._normalize_chat_id(b)

    async def _register_channel_handler(self) -> None:
        if self.uses_review_bot():
            logger.info("Review bot configured — skipping Telethon channel reply handler")
            return
        if not self.client:
            return
        chat_ids: list[int] = []
        for kind in ("default", "freelancer", "linkedin"):
            if not self._channel_enabled(kind):
                continue
            entity = await self._get_channel_entity(kind)
            if entity and entity.id not in chat_ids:
                chat_ids.append(entity.id)
        if not chat_ids:
            return
        if self._channel_handler_registered and self._channel_handler_chat_ids == chat_ids:
            return
        if self._channel_handler_registered:
            try:
                self.client.remove_event_handler(self._on_channel_message)
            except Exception:
                logger.debug("Could not remove previous channel handler", exc_info=True)
        self.client.add_event_handler(
            self._on_channel_message,
            events.NewMessage(chats=chat_ids),
        )
        self._channel_handler_registered = True
        self._channel_handler_chat_ids = list(chat_ids)
        logger.info("Listening for review replies in channel(s): %s", chat_ids)

    async def test_channel_notifications(self) -> dict:
        """Send sample notifications to the configured channel for testing."""
        if not self.connected:
            return {"ok": False, "error": "Telegram not connected. Connect in Settings → Telegram first."}
        if not self._channel_enabled():
            return {"ok": False, "error": "TELEGRAM_CHANNEL_ID not set (Freelancer bids check channel)"}

        channel_id = await self._resolve_channel()
        if not channel_id:
            return {
                "ok": False,
                "error": "Could not join or resolve the channel. Check the invite link and that your account is the channel owner.",
            }

        steps: list[dict] = []

        intro = await self._send_channel_message(
            "🧪 FREELANCER BIDS CHECK — CHANNEL TEST\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "@KayaProjectsBot review and bid alerts are sent here.",
            channel_kind="default",
        )
        steps.append({"type": "intro", "ok": bool(intro)})

        sample = Project(
            freelancer_project_id="99999999",
            title="[TEST] Sample project",
            description="Sample project description for channel notification test.",
            proposal="Hello,\n\nThis is a test proposal to verify channel notifications are working.",
            bid_amount=250.0,
            bid_duration=5,
            duration_type="days",
            currency="USD",
            confidence=72,
            budget_text="$250 USD",
            review_reason="Test — confidence below auto-bid threshold",
        )

        success_msg = await self._send_channel_message(format_bid_success(sample))
        steps.append({"type": "bid_success", "ok": bool(success_msg)})

        failed_msg = await self._send_channel_message(
            format_bid_failed(sample, "Test failure reason — sample error message.")
        )
        steps.append({"type": "bid_failed", "ok": bool(failed_msg)})

        db = SessionLocal()
        try:
            for old in db.query(Project).filter_by(freelancer_project_id="CHANNEL_TEST").all():
                db.delete(old)
            db.commit()

            test_project = Project(
                freelancer_project_id="CHANNEL_TEST",
                title="[TEST] Channel review test",
                description=sample.description,
                raw_message=sample.description,
                budget_text="$250 USD",
                status="pending_review",
                confidence=72,
                review_reason="Channel test — reply sent to approve or cancel to decline",
                currency="USD",
                source="telegram_bot",
            )
            db.add(test_project)
            db.commit()
            db.refresh(test_project)

            review_msg = await self._send_channel_message(
                format_review_request(test_project),
                parse_mode="html",
            )
            if review_msg:
                test_project.review_channel_message_id = review_msg.id
                test_project.review_channel_chat_id = getattr(review_msg, "chat_id", None) or channel_id
                test_project.review_notified_at = datetime.now(timezone.utc)
                db.commit()
            steps.append({
                "type": "review_request",
                "ok": bool(review_msg),
                "project_id": test_project.id,
            })
        finally:
            db.close()

        ok = all(step["ok"] for step in steps)
        return {
            "ok": ok,
            "channel_id": channel_id,
            "steps": steps,
            "hint": "Check your channel for 4 messages. Reply sent or cancel to the REVIEW REQUIRED message to test approval.",
        }

    def set_update_callback(self, cb: Callable[[], None]) -> None:
        self._on_update = cb

    def abort_bid_if_active(self, project_db_id: int) -> None:
        if self.active_project_db_id == project_db_id:
            logger.info("Aborting active bid flow for project db id %s", project_db_id)
            self._reset_bid_state()
        if self._bid_flow_task and not self._bid_flow_task.done():
            self._bid_flow_task.cancel()
            self._bid_flow_task = None

    def _notify(self) -> None:
        if self._on_update:
            self._on_update()

    def _today_utc(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def get_bids_today(self, db: Session) -> int:
        start = datetime.strptime(self._today_utc(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        return (
            db.query(Project)
            .filter(
                Project.status == "submitted",
                Project.submitted_at.isnot(None),
                Project.submitted_at >= start,
                Project.submitted_at < end,
            )
            .count()
        )

    def can_bid_today(self, db: Session) -> bool:
        return self.get_bids_today(db) < settings.max_bids_per_day

    def set_automation_enabled(self, enabled: bool) -> None:
        self.automation_enabled = enabled

    def intake_allowed(self) -> bool:
        """Whether automated project intake (bot, API poll, channel posts) may run."""
        return self.automation_enabled

    def _clear_bid_queue(self) -> None:
        while not self._bid_queue.empty():
            try:
                self._bid_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def pause_automation(self) -> None:
        if not self.automation_enabled:
            return
        self.automation_enabled = False
        if self.active_project_db_id:
            self.abort_bid_if_active(self.active_project_db_id)
        elif self._bid_flow_task and not self._bid_flow_task.done():
            self._bid_flow_task.cancel()
            self._bid_flow_task = None
            self._reset_bid_state()
        self._clear_bid_queue()
        logger.info("Automation paused — new projects and bids will not be processed")
        self._notify()

    async def resume_automation(self) -> None:
        if self.automation_enabled:
            return
        self.automation_enabled = True
        if not self.connected and settings.telegram_api_id and settings.telegram_api_hash:
            await self.start()
        db = SessionLocal()
        try:
            queued = db.query(Project).filter_by(status="queued").order_by(Project.id).all()
            for project in queued:
                if self.can_bid_today(db):
                    await self.enqueue_bid(project.id)
        finally:
            db.close()
        logger.info("Automation resumed")
        if self._channel_enabled("freelancer"):
            sent = await self.renotify_pending_freelancer_projects()
            if sent:
                logger.info("Re-sent %s pending Freelancer review(s) after resume", sent)
        await self._register_channel_handler()
        self._notify()

    async def start(self) -> None:
        if not settings.telegram_api_id or not str(settings.telegram_api_hash or "").strip():
            raise ValueError(
                "Telegram API ID and hash are required in backend/.env "
                "(https://my.telegram.org). On VPS+PC mode, set them on the PC worker, not the VPS."
            )

        if self.client and self.connected:
            return

        if self.client:
            await self.client.disconnect()

        self.client = TelegramClient(
            str(SESSION_PATH),
            int(settings.telegram_api_id),
            str(settings.telegram_api_hash).strip(),
        )
        await self.client.connect()

        if not await self.client.is_user_authorized():
            self.needs_auth = True
            self.connected = False
            return

        self.connected = True
        self.needs_auth = False
        self._bootstrap_persisted_channel_ids()
        bot = settings.telegram_bot_username.lstrip("@")
        self.client.add_event_handler(
            self._on_new_message,
            events.NewMessage(from_users=bot),
        )
        if self._channel_enabled() or self._channel_enabled("freelancer") or self._channel_enabled("linkedin"):
            await self._register_channel_handler()
            if self.automation_enabled:
                sent = await self.renotify_pending_freelancer_projects()
                if sent:
                    logger.info("Re-sent %s pending Freelancer review(s) to channel", sent)
                li_sent = await self.renotify_pending_linkedin_jobs()
                if li_sent.get("sent"):
                    logger.info(
                        "Re-sent %s pending LinkedIn Job Found message(s) to channel",
                        li_sent["sent"],
                    )
        self.running = True
        self._processor_task = asyncio.create_task(self._process_bid_queue())
        if self.automation_enabled:
            await self._enqueue_queued_projects()
        logger.info("Telegram client started, listening to @%s", bot)

    async def _enqueue_queued_projects(self) -> None:
        """Re-queue bot bids that were left in queued status across restarts."""
        db = SessionLocal()
        try:
            queued = db.query(Project).filter_by(status="queued").order_by(Project.id).all()
            for project in queued:
                if self.can_bid_today(db):
                    await self.enqueue_bid(project.id)
            if queued:
                logger.info("Re-enqueued %s queued project(s) after Telegram start", len(queued))
        finally:
            db.close()

    async def request_login_code(self) -> None:
        if not self.client:
            self.client = TelegramClient(
                str(SESSION_PATH),
                settings.telegram_api_id,
                settings.telegram_api_hash,
            )
            await self.client.connect()
        sent = await self.client.send_code_request(settings.telegram_phone)
        self.auth_phone_code_hash = sent.phone_code_hash
        self.needs_auth = True

    async def confirm_login(self, code: str, password: str | None = None) -> None:
        if not self.client or not self.auth_phone_code_hash:
            raise ValueError("Call request_login_code first")
        try:
            await self.client.sign_in(
                settings.telegram_phone,
                code,
                phone_code_hash=self.auth_phone_code_hash,
            )
        except Exception as exc:
            if "Two-steps verification" in str(exc) or "password" in str(exc).lower():
                if not password:
                    raise ValueError("Two-factor password required") from exc
                await self.client.sign_in(password=password)
            else:
                raise
        self.needs_auth = False
        await self.start()

    async def stop(self) -> None:
        self.running = False
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass
        if self.client:
            await self.client.disconnect()
            self.client = None
        self.connected = False
        self._channel_handler_registered = False
        self._channel_handler_chat_ids = []
        self._channel_entities.clear()
        self._channel_flood_until.clear()

    async def enqueue_bid(self, project_db_id: int) -> None:
        if not self.automation_enabled:
            logger.info("Automation paused — bid not queued for project %s", project_db_id)
            return
        if settings.test_mode:
            logger.info("Test mode: bid not sent for project %s", project_db_id)
            db = SessionLocal()
            try:
                project = db.get(Project, project_db_id)
                if project and project.proposal and project.status == "queued":
                    project.status = "test_ready"
                    db.commit()
                    self._notify()
            finally:
                db.close()
            return
        await self._bid_queue.put(project_db_id)

    async def _process_bid_queue(self) -> None:
        while self.running:
            try:
                project_id = await asyncio.wait_for(self._bid_queue.get(), timeout=2.0)
            except asyncio.TimeoutError:
                continue
            if not self.automation_enabled:
                continue
            if self.step != BidStep.IDLE:
                db = SessionLocal()
                try:
                    project = db.get(Project, project_id)
                    if project and project.status == "queued":
                        await asyncio.sleep(5)
                        await self._bid_queue.put(project_id)
                finally:
                    db.close()
                continue
            db = SessionLocal()
            try:
                project = db.get(Project, project_id)
                if not project or project.status != "queued":
                    continue
                if not self.can_bid_today(db):
                    project.status = "failed"
                    project.error_message = "Daily bid limit reached"
                    db.commit()
                    await self._dispatch_channel_notification(
                        self._notify_bid_failed(project.id, project.error_message)
                    )
                    continue
                await self._start_bid_flow(project_id, db)
            finally:
                db.close()

    async def _start_bid_flow(self, project_db_id: int, db: Session) -> None:
        project = db.get(Project, project_db_id)
        if not project or not project.proposal or project.status != "queued":
            return

        message = await self._find_project_message(project)
        if not message:
            project.status = "failed"
            project.error_message = "Could not find original Telegram message"
            db.commit()
            await self._dispatch_channel_notification(
                self._notify_bid_failed(project.id, project.error_message)
            )
            self._notify()
            return

        # Set bid state before clicking so fast bot replies are not missed.
        self.step = BidStep.AWAITING_PROPOSAL_PROMPT
        self.active_project_db_id = project_db_id
        self.active_freelancer_id = project.freelancer_project_id
        self.pending_proposal = project.proposal
        self.pending_amount = project.bid_amount
        self.pending_duration = project.bid_duration

        project.status = "bidding"
        db.commit()
        self._notify()

        clicked = await self._click_button(message, POST_BID_LABELS)
        if not clicked:
            self._reset_bid_state()
            project.status = "failed"
            project.error_message = 'Could not click "Post bid" button'
            db.commit()
            await self._dispatch_channel_notification(
                self._notify_bid_failed(project.id, project.error_message)
            )
            self._notify()
            return

        logger.info("Clicked Post bid for project %s, waiting for proposal prompt", project.freelancer_project_id)
        self._bid_flow_task = asyncio.create_task(self._poll_bid_advancement(attempts=90, delay=1.0))
        await self._bid_flow_task

    async def _find_project_message(self, project: Project) -> Message | None:
        if not self.client:
            return None
        bot = settings.telegram_bot_username.lstrip("@")
        if project.telegram_message_id:
            msg = await self.client.get_messages(bot, ids=project.telegram_message_id)
            if msg:
                return msg
        async for msg in self.client.iter_messages(bot, limit=100):
            if project.freelancer_project_id and project.freelancer_project_id in (msg.text or ""):
                return msg
            if project.raw_message and msg.text and project.raw_message[:120] in msg.text:
                return msg
        return None

    async def _click_button(self, message: Message, labels: tuple[str, ...]) -> bool:
        if not message.buttons:
            return False
        for row in message.buttons:
            for button in row:
                label = (button.text or "").strip()
                if label in labels or label.lower() in [l.lower() for l in labels]:
                    await message.click(text=label)
                    return True
        return False

    async def _resolve_channel_kind(self, chat_id: int) -> str | None:
        for kind in ("default", "freelancer", "linkedin"):
            if not self._channel_enabled(kind):
                continue
            entity = self._channel_entities.get(kind)
            if entity is None and not self._channel_flood_blocked(kind):
                entity = await self._get_channel_entity(kind)
            channel_id = entity.id if entity is not None else self._persisted_channel_ids.get(kind)
            if channel_id is not None and self._chat_ids_match(chat_id, channel_id):
                return kind
        return None

    @staticmethod
    def _normalize_review_keyword(text: str) -> str | None:
        cleaned = (text or "").strip().lower().strip(".,!?")
        if cleaned in ("send", "sent", "cancel", "create", "resume", "regenerate"):
            return cleaned
        return None

    async def _on_channel_message(self, event: events.NewMessage.Event) -> None:
        text = self._normalize_review_keyword(event.message.text or "")
        if text is None:
            return

        channel_kind = await self._resolve_channel_kind(event.chat_id)
        if channel_kind is None:
            logger.debug(
                "Channel reply ignored — unknown chat_id %s (normalized %s)",
                event.chat_id,
                self._normalize_chat_id(event.chat_id),
            )
            return

        reply = event.message.reply_to
        if not reply or not getattr(reply, "reply_to_msg_id", None):
            return

        if channel_kind == "linkedin":
            if text not in ("create", "cancel", "resume", "regenerate"):
                return
            await self._handle_linkedin_channel_reply(text, event)
            return

        # Bot channel: sent (send accepted as alias). API channel: send only.
        if channel_kind == "default" and text not in ("sent", "send", "cancel"):
            return
        if channel_kind == "freelancer" and text not in ("send", "cancel"):
            return
        if channel_kind == "default" and text == "send":
            text = "sent"

        from app.services.project_service import SOURCE_FREELANCER_API, SOURCE_TELEGRAM_BOT

        expected_source = (
            SOURCE_FREELANCER_API if channel_kind == "freelancer" else SOURCE_TELEGRAM_BOT
        )

        db = SessionLocal()
        try:
            project = (
                db.query(Project)
                .filter(
                    Project.review_channel_message_id == reply.reply_to_msg_id,
                    Project.source == expected_source,
                )
                .first()
            )
            if not project or project.status != "pending_review":
                logger.info(
                    "Channel reply ignored — no pending project for msg_id=%s source=%s",
                    reply.reply_to_msg_id,
                    expected_source,
                )
                return
            if not self._chat_ids_match(project.review_channel_chat_id, event.chat_id):
                logger.warning(
                    "Channel reply ignored — project %s chat mismatch (%s vs %s)",
                    project.id,
                    project.review_channel_chat_id,
                    event.chat_id,
                )
                return

            if text == "cancel":
                await self._handle_channel_decline(project, db, event)
            elif channel_kind == "default":
                await self._handle_bot_channel_approve(project, db, event)
            else:
                await self._handle_api_channel_approve(project, db, event)
        except Exception:
            logger.exception("Error handling channel review reply")
        finally:
            db.close()

    async def _handle_linkedin_channel_reply(
        self, text: str, event: events.NewMessage.Event
    ) -> None:
        reply = event.message.reply_to
        if not reply:
            return

        db = SessionLocal()
        try:
            if text == "regenerate":
                row = (
                    db.query(AtsResume)
                    .filter(AtsResume.channel_message_id == reply.reply_to_msg_id)
                    .first()
                )
                if not row:
                    logger.info(
                        "LinkedIn regenerate reply ignored — no ATS resume for msg_id=%s",
                        reply.reply_to_msg_id,
                    )
                    return
                if row.channel_chat_id is not None and not self._chat_ids_match(
                    row.channel_chat_id, event.chat_id
                ):
                    return
                from app.ats.service import enqueue_for_job

                job = db.get(LinkedInJob, row.linkedin_job_db_id)
                row.status = "generating"
                row.error_message = None
                db.commit()
                enqueue_for_job(row.linkedin_job_db_id, force=True, repost=True)
                title = html.escape((job.title if job else None) or "Untitled role")[:80]
                score = f"{row.total_score}/100" if row.total_score is not None else "—"
                await self._send_channel_message(
                    f"🔄 Regenerating ATS resume for <b>{title}</b> "
                    f"(previous score {score})… A new message with the updated file and score will post here.",
                    channel_kind="linkedin",
                    reply_to=event.message.id,
                    parse_mode="html",
                )
                return

            if text == "resume":
                job = (
                    db.query(LinkedInJob)
                    .filter(LinkedInJob.review_channel_message_id == reply.reply_to_msg_id)
                    .first()
                )
                if not job:
                    logger.info(
                        "LinkedIn resume reply ignored — no job for msg_id=%s",
                        reply.reply_to_msg_id,
                    )
                    return
                if not self._chat_ids_match(job.review_channel_chat_id, event.chat_id):
                    return
                from app.ats.service import enqueue_for_job, get_or_create_ats_row
                from app.telegram.channel_messages import format_linkedin_ats_creating

                row = get_or_create_ats_row(db, job.id)
                row.status = "generating"
                row.error_message = None
                db.commit()
                enqueue_for_job(job.id, force=True, repost=True)
                await self._send_channel_message(
                    format_linkedin_ats_creating(job, queued=False),
                    channel_kind="linkedin",
                    reply_to=event.message.id,
                    parse_mode="html",
                )
                return

            job = (
                db.query(LinkedInJob)
                .filter(
                    LinkedInJob.review_channel_message_id == reply.reply_to_msg_id,
                    LinkedInJob.status.in_(("matched", "draft")),
                )
                .first()
            )
            if not job:
                logger.info(
                    "LinkedIn channel reply ignored — no job for msg_id=%s",
                    reply.reply_to_msg_id,
                )
                return
            if not self._chat_ids_match(job.review_channel_chat_id, event.chat_id):
                return

            if text == "cancel":
                job.status = "skipped"
                job.match_reason = (job.match_reason or "") + " · Declined via Telegram channel"
                job.error_message = None
                db.commit()
                return

            # Already composed — re-post draft instead of calling AI again
            if job.status == "draft" and (job.email_body or "").strip():
                await self.notify_linkedin_job_draft(job)
                return

            await self._send_channel_message(
                "⏳ Composing application email with AI…",
                channel_kind="linkedin",
            )
            from app.linkedin.service import compose_linkedin_draft
            from app.linkedin.settings import load_linkedin_settings

            cfg = load_linkedin_settings(db)
            try:
                await compose_linkedin_draft(db, job, cfg)
                db.refresh(job)
            except Exception as exc:
                logger.exception("LinkedIn create draft failed for job %s", job.id)
                job.status = "failed"
                job.error_message = str(exc)
                db.commit()
                await self._send_channel_message(
                    f"❌ Failed to compose email: {exc}",
                    channel_kind="linkedin",
                )
                return

            await self.notify_linkedin_job_draft(job)
        except Exception:
            logger.exception("Error handling LinkedIn channel reply")
        finally:
            db.close()

    async def _handle_channel_decline(
        self, project: Project, db: Session, event: events.NewMessage.Event
    ) -> None:
        from app.services.project_service import skip_project_review

        skip_project_review(db, project, "Declined via Telegram channel")
        await self._send_channel_message(
            format_review_declined(project),
            reply_to=event.message.id,
            chat_id=event.chat_id,
        )
        self._notify()

    async def _handle_bot_channel_approve(
        self, project: Project, db: Session, event: events.NewMessage.Event
    ) -> None:
        """Freelancer bids check channel — bid via @KayaProjectsBot automation."""
        from app.services.project_service import approve_project_for_bid

        if not self.can_bid_today(db):
            await self._send_channel_message(
                f"⚠️ Daily bid limit reached ({settings.max_bids_per_day}). Cannot send project "
                f"{project.freelancer_project_id or project.id}.",
                reply_to=event.message.id,
                chat_id=event.chat_id,
            )
            return

        project_id = project.id
        await self._send_channel_message(
            format_review_approved(project),
            reply_to=event.message.id,
            chat_id=event.chat_id,
        )
        try:
            await approve_project_for_bid(db, project)
        except Exception as exc:
            project.status = "failed"
            project.error_message = f"Proposal generation failed: {exc}"
            db.commit()
            await self._notify_bid_failed(project_id, project.error_message, stage="Proposal generation")
            self._notify()
            return

        await self.enqueue_bid(project_id)
        self._notify()

    async def _handle_api_channel_approve(
        self, project: Project, db: Session, event: events.NewMessage.Event
    ) -> None:
        """Freelancer.com API bidding removed."""
        await self._send_channel_message(
            "⚠️ Freelancer API bidding has been removed from LinkedIn Job Finder.",
            reply_to=event.message.id,
            chat_id=event.chat_id,
        )

    async def _handle_channel_approve(
        self, project: Project, db: Session, event: events.NewMessage.Event
    ) -> None:
        """Legacy entry — route by project source."""
        from app.services.project_service import SOURCE_FREELANCER_API

        if (project.source or "") == SOURCE_FREELANCER_API:
            await self._handle_api_channel_approve(project, db, event)
        else:
            await self._handle_bot_channel_approve(project, db, event)

    async def _on_new_message(self, event: events.NewMessage.Event) -> None:
        text = (event.message.text or "").strip()
        if not text or event.message.out:
            return
        if not self.automation_enabled and self.step == BidStep.IDLE:
            return

        db = SessionLocal()
        try:
            if self.step == BidStep.IDLE:
                await self._handle_project_announcement(event.message, text, db)
            else:
                advanced = await self._try_advance_bid_step(event.message, text, db)
                if advanced and self.step != BidStep.IDLE:
                    attempts = 60 if self.step == BidStep.AWAITING_RESULT else 20
                    asyncio.create_task(self._poll_bid_advancement(attempts=attempts, delay=1.0))
        except Exception:
            logger.exception("Error handling Telegram message")
        finally:
            db.close()

    @staticmethod
    def _text_has_marker(text: str, markers: tuple[str, ...]) -> bool:
        lower = text.lower()
        return any(marker in lower for marker in markers)

    def _is_proposal_prompt(self, text: str) -> bool:
        return self._text_has_marker(text, PROPOSAL_PROMPT_MARKERS)

    def _is_amount_prompt(self, text: str) -> bool:
        return self._text_has_marker(text, AMOUNT_PROMPT_MARKERS)

    def _is_duration_prompt(self, text: str) -> bool:
        return self._text_has_marker(text, DURATION_PROMPT_MARKERS)

    def _is_bid_success_message(self, text: str) -> bool:
        lower = text.lower()
        return (
            "bid sent to project" in lower
            or ("done" in lower and "bid sent" in lower)
            or ("remaining bids" in lower and "bid sent" in lower)
        )

    def _is_bid_failure_message(self, text: str) -> bool:
        if "موجودی" in text or "کافی نیست" in text:
            return True
        lower = text.lower()
        failure_markers = (
            "could not",
            "unable to",
            "failed to",
            "not enough",
            "insufficient",
            "denied",
            "rejected",
            "not allowed",
            "limit reached",
        )
        return any(marker in lower for marker in failure_markers)

    def _is_definitive_bid_result(self, text: str) -> bool:
        return self._is_bid_success_message(text) or self._is_bid_failure_message(text)

    def _is_new_bid_result_message(self, message: Message) -> bool:
        if self._result_after_message_id is None:
            return True
        return message.id > self._result_after_message_id

    def _is_bid_flow_prompt(self, text: str) -> bool:
        lower = text.lower()
        return (
            self._is_proposal_prompt(text)
            or self._is_amount_prompt(text)
            or self._is_duration_prompt(text)
            or "are you sure" in lower
        )

    async def _finalize_bid_result(self, text: str, db: Session) -> bool:
        project = db.get(Project, self.active_project_db_id) if self.active_project_db_id else None
        if not project:
            self._reset_bid_state()
            return True
        project_id = project.id
        if self._is_bid_success_message(text):
            pid = self._extract_project_id(text) or self.active_freelancer_id
            project.status = "submitted"
            project.submitted_at = datetime.now(timezone.utc)
            project.error_message = None
            if pid:
                project.freelancer_project_id = pid
            db.commit()
            logger.info("Bid submitted successfully for project %s", pid)
            await self._dispatch_channel_notification(self._notify_bid_success(project_id))
        elif self._is_bid_failure_message(text):
            project.status = "failed"
            project.error_message = text
            db.commit()
            logger.warning("Bid failed for project %s: %s", self.active_freelancer_id, text[:200])
            await self._dispatch_channel_notification(self._notify_bid_failed(project_id, text))
        else:
            logger.debug("Ignoring non-definitive bid result: %s", text[:120])
            return False
        self._reset_bid_state()
        self._notify()
        return True

    def _matches_current_step_prompt(self, message: Message, text: str) -> bool:
        if self.step == BidStep.AWAITING_PROPOSAL_PROMPT:
            return self._is_proposal_prompt(text)
        if self.step == BidStep.AWAITING_AMOUNT_PROMPT:
            return self._is_amount_prompt(text)
        if self.step == BidStep.AWAITING_DURATION_PROMPT:
            return self._is_duration_prompt(text)
        if self.step == BidStep.AWAITING_CONFIRM:
            return "are you sure" in text.lower()
        if self.step == BidStep.AWAITING_RESULT:
            if not self._is_new_bid_result_message(message):
                return False
            if self._is_bid_flow_prompt(text) or self._is_project_listing(message, text):
                return False
            pid = self._extract_project_id(text)
            if pid and self.active_freelancer_id and pid != self.active_freelancer_id:
                return False
            return self._is_definitive_bid_result(text)
        return False

    def _result_matches_active_bid(self, text: str) -> bool:
        pid = self._extract_project_id(text)
        if pid and self.active_freelancer_id and pid != self.active_freelancer_id:
            return False
        return True

    def _prompt_matches_active_project(self, text: str) -> bool:
        if not self.active_freelancer_id:
            return True
        if self.active_freelancer_id in text:
            return True
        prompt_pid = self._extract_project_id(text)
        return prompt_pid is None or prompt_pid == self.active_freelancer_id

    def _is_project_listing(self, message: Message, text: str) -> bool:
        if not message.buttons or not self._has_post_bid_button(message):
            return False
        return bool(self._extract_project_id(text))

    def _has_post_bid_button(self, message: Message) -> bool:
        if not message.buttons:
            return False
        return any(
            (btn.text or "").strip().lower() == "post bid"
            for row in message.buttons
            for btn in row
        )

    async def _poll_bid_advancement(self, attempts: int = 15, delay: float = 1.0) -> None:
        """Poll recent bot messages (newest first) and advance the bid state machine."""
        if not self.client or self.step == BidStep.IDLE:
            return
        bot = settings.telegram_bot_username.lstrip("@")
        for _ in range(attempts):
            if self.step == BidStep.IDLE:
                return
            messages = await self.client.get_messages(bot, limit=12)
            advanced = False
            db = SessionLocal()
            try:
                for msg in messages:
                    if msg.out or not (msg.text or "").strip():
                        continue
                    text = msg.text.strip()
                    if not self._matches_current_step_prompt(msg, text):
                        continue
                    if await self._try_advance_bid_step(msg, text, db):
                        advanced = True
                        break
            finally:
                db.close()
            if advanced and self.step != BidStep.IDLE:
                await asyncio.sleep(delay)
                continue
            if self.step == BidStep.IDLE:
                return
            await asyncio.sleep(delay)
        if self.step != BidStep.IDLE:
            logger.warning("Bid flow timed out at step %s for project %s", self.step.value, self.active_freelancer_id)
            db = SessionLocal()
            try:
                project = db.get(Project, self.active_project_db_id) if self.active_project_db_id else None
                if project and project.status in ("bidding", "queued", "generating"):
                    project.status = "failed"
                    project.error_message = f"Timed out during bid flow at step {self.step.value}"
                    db.commit()
                    await self._dispatch_channel_notification(
                        self._notify_bid_failed(project.id, project.error_message)
                    )
                self._reset_bid_state()
                self._notify()
            finally:
                db.close()

    async def _try_advance_bid_step(self, message: Message, text: str, db: Session) -> bool:
        if not self.client or self.step == BidStep.IDLE:
            return False
        if self._is_project_listing(message, text):
            return False

        bot = settings.telegram_bot_username.lstrip("@")

        if self.step == BidStep.AWAITING_PROPOSAL_PROMPT:
            if not self._is_proposal_prompt(text) or not self._prompt_matches_active_project(text):
                return False
            async with self._bid_lock:
                if self.step != BidStep.AWAITING_PROPOSAL_PROMPT:
                    return False
                await asyncio.sleep(0.5)
                await self.client.send_message(bot, self.pending_proposal or "")
                self.step = BidStep.AWAITING_AMOUNT_PROMPT
                logger.info("Sent proposal for project %s", self.active_freelancer_id)
                self._notify()
                return True

        if self.step == BidStep.AWAITING_AMOUNT_PROMPT:
            if not self._is_amount_prompt(text):
                return False
            async with self._bid_lock:
                if self.step != BidStep.AWAITING_AMOUNT_PROMPT:
                    return False
                if self.pending_amount is None:
                    logger.error("No bid amount stored for project %s", self.active_freelancer_id)
                    return False
                amount_str = str(int(self.pending_amount)) if float(self.pending_amount).is_integer() else str(self.pending_amount)
                await asyncio.sleep(0.5)
                await self.client.send_message(bot, amount_str)
                self.step = BidStep.AWAITING_DURATION_PROMPT
                logger.info("Sent bid amount %s for project %s", amount_str, self.active_freelancer_id)
                self._notify()
                return True

        if self.step == BidStep.AWAITING_DURATION_PROMPT:
            if not self._is_duration_prompt(text):
                return False
            async with self._bid_lock:
                if self.step != BidStep.AWAITING_DURATION_PROMPT:
                    return False
                await asyncio.sleep(0.5)
                await self.client.send_message(bot, str(self.pending_duration or 7))
                self.step = BidStep.AWAITING_CONFIRM
                logger.info("Sent bid duration for project %s", self.active_freelancer_id)
                self._notify()
                return True

        if self.step == BidStep.AWAITING_CONFIRM:
            if "are you sure" not in text.lower() or not message.buttons:
                return False
            async with self._bid_lock:
                if self.step != BidStep.AWAITING_CONFIRM:
                    return False
                clicked = await self._click_button(message, YES_LABELS)
                if not clicked:
                    return False
                self._result_after_message_id = message.id
                self.step = BidStep.AWAITING_RESULT
                logger.info("Confirmed bid for project %s, waiting for result", self.active_freelancer_id)
                self._notify()
                return True

        if self.step == BidStep.AWAITING_RESULT:
            if not self._is_new_bid_result_message(message):
                return False
            if self._is_bid_flow_prompt(text) or self._is_project_listing(message, text):
                return False
            if not self._result_matches_active_bid(text):
                return False
            if not self._is_definitive_bid_result(text):
                return False
            async with self._bid_lock:
                if self.step != BidStep.AWAITING_RESULT:
                    return False
                return await self._finalize_bid_result(text, db)

        return False

    async def _handle_project_announcement(self, message: Message, text: str, db: Session) -> None:
        if not message.buttons:
            return
        has_post_bid = any(
            (btn.text or "").strip().lower() == "post bid"
            for row in message.buttons
            for btn in row
        )
        if not has_post_bid:
            return

        if not self.intake_allowed():
            return

        project_id = self._extract_project_id(text)
        if project_id:
            existing = db.query(Project).filter_by(freelancer_project_id=project_id).first()
            if existing:
                return

        from app.ai.evaluator import generate_proposal, screen_bot_project
        from app.filters.pre_match import evaluate_pre_match
        from app.services.project_service import (
            SOURCE_TELEGRAM_BOT,
            apply_proposal_for_telegram,
            apply_screening,
            create_project_from_message,
        )

        project = create_project_from_message(
            db,
            text=text,
            message_id=message.id,
            freelancer_project_id=project_id,
            source=SOURCE_TELEGRAM_BOT,
        )

        pre_ok, pre_reason = evaluate_pre_match(text, db=db)
        if not pre_ok:
            project.status = "skipped"
            project.skip_reason = f"Pre-match: {pre_reason}"
            db.commit()
            logger.info("Bot project %s pre-match filtered: %s", project_id or project.id, pre_reason)
            self._notify()
            return

        try:
            screening = await screen_bot_project(text)
            apply_screening(db, project, screening, settings.auto_bid_confidence_threshold)

            if project.status == "generating":
                proposal = await generate_proposal(text)
                apply_proposal_for_telegram(db, project, proposal)
                if not settings.test_mode and self.can_bid_today(db):
                    await self.enqueue_bid(project.id)
            elif project.status == "pending_review":
                if self.intake_allowed():
                    await self._dispatch_channel_notification(self._notify_review_request(project.id))
        except Exception as exc:
            project.status = "failed"
            project.error_message = str(exc)
            db.commit()
            await self._dispatch_channel_notification(
                self._notify_bid_failed(project.id, project.error_message, stage="AI processing")
            )

        self._notify()

    def _reset_bid_state(self) -> None:
        self.step = BidStep.IDLE
        self.active_project_db_id = None
        self.active_freelancer_id = None
        self.pending_proposal = None
        self.pending_amount = None
        self.pending_duration = None
        self._result_after_message_id = None

    @staticmethod
    def _extract_project_id(text: str) -> str | None:
        patterns = [
            r"project\s+#?(\d{6,})",
            r"project\s+id[:\s]+`?(\d{6,})`?",
            r"#(\d{6,})",
            r"ID[:\s]+`?(\d{6,})`?",
            r"/projects/(\d+)",
            r"jobs/(\d{6,})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        return None


telegram_service = TelegramService()
