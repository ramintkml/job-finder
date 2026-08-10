"""Structured Telegram channel notification messages."""

from __future__ import annotations

import html
import re

from app.database import LinkedInJob, Project
from app.services.project_service import SOURCE_FREELANCER_API, SOURCE_TELEGRAM_BOT

MAX_DESCRIPTION = 2500
MAX_PROPOSAL = 1500
MAX_ERROR = 1500
_DIVIDER = "━━━━━━━━━━━━━━"


def _project_code(project: Project) -> str:
    return project.freelancer_project_id or f"#{project.id}"


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def _format_amount(project: Project) -> str:
    if project.bid_amount is None:
        return "—"
    amount = (
        str(int(project.bid_amount))
        if float(project.bid_amount).is_integer()
        else str(project.bid_amount)
    )
    return f"{amount} {project.currency or 'USD'}"


def _format_duration(project: Project) -> str:
    if project.bid_duration is None:
        return "—"
    if project.duration_type == "hours_per_week":
        return f"{project.bid_duration} hours/week"
    return f"{project.bid_duration} days"


def _display_budget(project: Project) -> str:
    raw = (project.budget_text or "").strip()
    if not raw:
        match = re.search(
            r"(?:fixed|hourly):\s*\$?\s*[\d,]+(?:\s*-\s*[\d,]+)?\s*USD",
            project.description or "",
            re.IGNORECASE,
        )
        if match:
            return match.group(0).strip()
        match = re.search(
            r"Budget:\s*\$?[\d,]+(?:\s*-\s*\$?[\d,]+)?\s*USD",
            project.description or "",
            re.IGNORECASE,
        )
        if match:
            return re.sub(r"^budget:\s*", "", match.group(0), flags=re.IGNORECASE).strip()
        return "—"
    cleaned = re.sub(r"^budget:\s*", "", raw, flags=re.IGNORECASE).strip()
    return cleaned or raw


def _parse_description_sections(project: Project) -> tuple[str, str, str]:
    """Return (title, skills_line, body) for channel layout."""
    text = (project.description or "").strip()
    source = getattr(project, "source", None) or "telegram_bot"
    title = (project.title or "").strip()
    skills = ""
    body_lines: list[str] = []

    lines = [ln.rstrip() for ln in text.splitlines()]
    non_empty = [ln.strip() for ln in lines if ln.strip()]

    if source == SOURCE_FREELANCER_API:
        start = 0
        if non_empty:
            first = non_empty[0]
            project_header = re.match(
                r"Project\s*#\d+\s*[—–-]\s*(.+)",
                first,
                re.IGNORECASE,
            )
            if project_header:
                title = project_header.group(1).strip()
                start = 1
            elif not title:
                title = first
                start = 1

        for ln in non_empty[start:]:
            lower = ln.lower()
            if lower.startswith("skills:"):
                skills = ln
            elif lower.startswith("budget:"):
                continue
            elif re.match(r"^project\s*#\d+", ln, re.IGNORECASE):
                continue
            else:
                body_lines.append(ln)
    else:
        if non_empty:
            title = non_empty[0]
            body_lines = non_empty[1:]
        elif title:
            body_lines = []
        else:
            title = "Untitled project"
            body_lines = []

    body = "\n".join(body_lines).strip()
    if not title:
        title = "Untitled project"
    return title, skills, _truncate(body, MAX_DESCRIPTION)


def _blockquote_body(body: str) -> str:
    if not body.strip():
        return ""
    return f"<blockquote expandable>{_esc(body)}</blockquote>"


def _project_source_label(project: Project) -> str:
    source = getattr(project, "source", None) or SOURCE_TELEGRAM_BOT
    if source == SOURCE_FREELANCER_API:
        return "Freelancer API"
    return "Freelancer Bot (@KayaProjectsBot)"


def _linkedin_url_line(job: LinkedInJob) -> str:
    url = (job.job_url or "").strip()
    if not url.startswith("http"):
        return ""
    href = html.escape(url, quote=True)
    return f'<a href="{href}">باز کردن در لینکدین</a>'


def _linkedin_description_quote(job: LinkedInJob, *, limit: int = MAX_DESCRIPTION) -> str:
    description = _truncate(job.description or "", limit)
    return _blockquote_body(description)


def format_bid_success(project: Project, *, for_bot: bool = False) -> str:
    """Successful bid notice. for_bot=True uses HTML with collapsed proposal quote."""
    proposal = _truncate(project.proposal or "", MAX_PROPOSAL)
    if for_bot:
        parts = [
            "<b>✅ BID SUCCESS</b>",
            _DIVIDER,
            f"<b>Project:</b> {_esc(_project_code(project))}",
            f"<b>Amount:</b> {_esc(_format_amount(project))}",
            f"<b>Duration:</b> {_esc(_format_duration(project))}",
        ]
        if proposal.strip():
            parts.extend(["", "<b>Proposal:</b>", _blockquote_body(proposal)])
        return "\n".join(parts)

    return (
        "✅ BID SUCCESS\n"
        f"{_DIVIDER}\n"
        f"Project: {_project_code(project)}\n"
        f"Amount: {_format_amount(project)}\n"
        f"Duration: {_format_duration(project)}\n"
        "\n"
        "Proposal:\n"
        f"{proposal}"
    )


def format_bid_failed(project: Project, reason: str, stage: str = "Bidding") -> str:
    header = "❌ BID FAILED" if stage == "Bidding" else "❌ PROJECT FAILED"
    lines = [
        header,
        _DIVIDER,
        f"Project: {_project_code(project)}",
    ]
    if project.title and not project.freelancer_project_id:
        lines.append(f"Title: {_truncate(project.title, 200)}")
    if stage != "Bidding":
        lines.append(f"Stage: {stage}")
    lines.extend(["", "Reason:", _truncate(reason, MAX_ERROR)])
    return "\n".join(lines)


def format_review_request(project: Project, *, for_bot: bool = False) -> str:
    """HTML message for Telegram (use parse_mode='html')."""
    confidence = f"{project.confidence}%" if project.confidence is not None else "—"
    budget = _display_budget(project)
    source = getattr(project, "source", None) or "telegram_bot"
    has_proposal = bool((project.proposal or "").strip())
    title, skills, body = _parse_description_sections(project)

    if source == SOURCE_FREELANCER_API:
        send_hint = "🟢 send — generate proposal and submit bid on Freelancer.com"
    else:
        send_hint = "🟢 sent — generate proposal and bid via @KayaProjectsBot"

    parts = [
        "<b>📋 REVIEW REQUIRED</b>",
        _DIVIDER,
        f"<b>Project:</b> {_esc(_project_code(project))}",
        f"<b>Source:</b> {_esc(_project_source_label(project))}",
        f"<b>Confidence:</b> {_esc(confidence)}",
        f"<b>Budget:</b> {_esc(budget)}",
        "",
        "<b>Description:</b>",
        f"<b>{_esc(title)}</b>",
    ]

    if skills:
        parts.append(_esc(skills))

    quote = _blockquote_body(body)
    if quote:
        parts.append(quote)

    if source == SOURCE_FREELANCER_API and has_proposal:
        parts.extend([
            "",
            "<b>Proposal:</b>",
            f"<blockquote expandable>{_esc(_truncate(project.proposal or '', MAX_PROPOSAL))}</blockquote>",
        ])

    if for_bot:
        parts.extend(["", "Use the buttons below to send or skip."])
    else:
        parts.extend([
            "",
            "Reply to this message:",
            send_hint,
            "🔴 cancel — skip this project",
        ])
    return "\n".join(parts)


def format_review_approved(project: Project) -> str:
    source = getattr(project, "source", None) or "telegram_bot"
    if source == SOURCE_FREELANCER_API:
        if (project.proposal or "").strip():
            detail = "Submitting via Freelancer API..."
        else:
            detail = "Generating proposal, then submitting via Freelancer API..."
    else:
        detail = "Queuing bid via @KayaProjectsBot..."
    return (
        "⏳ SENDING BID\n"
        f"{_DIVIDER}\n"
        f"Project: {_project_code(project)}\n"
        f"{detail}"
    )


def format_review_declined(project: Project, *, auto: bool = False, timeout_minutes: int = 15) -> str:
    lines = [
        "🚫 REVIEW DECLINED",
        _DIVIDER,
        f"Project: {_project_code(project)}",
        "Bid will not be sent.",
    ]
    if auto:
        lines.append(f"⏱️ Auto-declined — no reply within {timeout_minutes} minutes.")
    return "\n".join(lines)


def format_linkedin_job_review_request(job: LinkedInJob, *, for_bot: bool = False) -> str:
    """HTML Telegram message for a newly matched LinkedIn job awaiting review."""
    phrase = (job.search_phrase or "جستجوی شما").strip()
    title = _truncate(job.title or "بدون عنوان", 200)
    company = _truncate(job.company or "—", 120)
    location = _truncate(job.location or "—", 120)
    description = _truncate(job.description or "", MAX_DESCRIPTION)
    score = f"{job.relevance_score}%" if job.relevance_score is not None else "—"

    parts = [
        f'<b>🚨 شغل پیدا شد برای «{_esc(phrase)}»</b>',
        _DIVIDER,
        f"<b>{_esc(title)}</b>",
        f"{_esc(company)} · {_esc(location)}",
        f"<b>تطابق رزومه:</b> {_esc(score)}",
        "",
        "<b>توضیحات:</b>",
    ]

    desc_quote = _blockquote_body(description)
    if desc_quote:
        parts.append(desc_quote)

    if job.job_url and not for_bot:
        url = html.escape(job.job_url.strip(), quote=True)
        parts.extend(["", f'<a href="{url}">باز کردن در لینکدین</a>'])

    if for_bot:
        parts.extend(["", "از دکمه‌های زیر استفاده کنید."])
    else:
        parts.extend([
            "",
            "به این پیام پاسخ دهید:",
            "🟢 <b>create</b> — ساخت ایمیل درخواست با هوش مصنوعی",
            "📄 <b>resume</b> — ساخت رزومه ATS",
            "🔴 <b>cancel</b> — رد کردن این شغل",
        ])
    return "\n".join(parts)


def format_linkedin_ats_creating(job: LinkedInJob, *, queued: bool = False) -> str:
    """Message shown right after Create resume — includes link + collapsed description."""
    title = _truncate(job.title or "بدون عنوان", 200)
    company = _truncate(job.company or "—", 120)
    status = (
        "⏳ رزومه ATS در صف ساخت است."
        if queued
        else "📄 در حال ساخت رزومه ATS…"
    )
    parts = [
        status,
        _DIVIDER,
        f"<b>{_esc(title)}</b>",
        f"{_esc(company)}",
    ]
    link = _linkedin_url_line(job)
    if link:
        parts.extend(["", link])
    parts.extend(["", "<b>توضیحات:</b>"])
    desc_quote = _linkedin_description_quote(job)
    if desc_quote:
        parts.append(desc_quote)
    else:
        parts.append("<i>توضیحی موجود نیست.</i>")
    parts.extend(["", "فایل و امتیاز اینجا ارسال می‌شود."])
    return "\n".join(parts)


def format_linkedin_ats_resume_caption(
    job: LinkedInJob,
    *,
    total_score: int | None = None,
    band: str | None = None,
    for_bot: bool = False,
) -> str:
    """HTML caption for ATS resume file (Telegram caption max 1024)."""
    title = _truncate(job.title or "بدون عنوان", 100)
    company = _truncate(job.company or "—", 60)

    if total_score is not None:
        score_bits = f"{int(total_score)}/100"
        if band:
            score_bits += f" ({_esc(band)})"
        score_line = f"<b>امتیاز ATS:</b> {score_bits}"
    else:
        score_line = "<b>امتیاز ATS:</b> —"

    parts = [
        f"<b>{_esc(title)}</b>",
        f"{_esc(company)}",
        score_line,
    ]
    link = _linkedin_url_line(job)
    if link:
        parts.extend(["", link])

    header = "\n".join(parts)
    footer = (
        "\n\nرزومه ATS پیوست شد.\nبا <b>ساخت مجدد</b> می‌توانید بهبود دهید."
        if for_bot
        else (
            "\n\nرزومه ATS پیوست شد (DOCX).\n\n"
            "به این پیام پاسخ دهید:\n"
            "🔄 <b>regenerate</b> — بهبود بر اساس راهنمای امتیاز و ارسال مجدد"
        )
    )
    budget = 880 - len(header) - len(footer) - len("<b>توضیحات:</b>\n") - len(
        "<blockquote expandable></blockquote>"
    )
    desc_parts: list[str] = []
    if budget > 40:
        desc_quote = _linkedin_description_quote(job, limit=max(40, budget))
        if desc_quote:
            desc_parts = ["", "<b>توضیحات:</b>", desc_quote]

    return "\n".join(parts + desc_parts) + footer


def format_linkedin_job_draft(job: LinkedInJob) -> str:
    """HTML Telegram message with AI-composed application email draft."""
    phrase = (job.search_phrase or "جستجوی شما").strip()
    title = _truncate(job.title or "بدون عنوان", 200)
    company = _truncate(job.company or "—", 120)
    recipient = (job.recipient_email or "").strip()

    subject = (job.email_subject or "").strip()
    body = _truncate(job.email_body or "", MAX_PROPOSAL)
    email_text = "\n".join(part for part in (f"Subject: {subject}" if subject else "", body) if part)

    parts = [
        f'<b>📧 پیش‌نویس ایمیل — «{_esc(phrase)}»</b>',
        _DIVIDER,
        f"<b>{_esc(title)}</b>",
        f"{_esc(company)}",
    ]
    if recipient:
        parts.append(f"<b>گیرنده:</b> {_esc(recipient)}")
    else:
        parts.append(
            "<b>گیرنده:</b> ایمیل استخدام‌کننده در آگهی نبود — در لینکدین اقدام کنید"
        )

    parts.extend(["", "<b>📧 ایمیل:</b>"])
    email_quote = _blockquote_body(email_text)
    if email_quote:
        parts.append(email_quote)

    if job.job_url:
        url = html.escape(job.job_url.strip(), quote=True)
        parts.extend(["", f'<a href="{url}">باز کردن در لینکدین</a>'])

    return "\n".join(parts)


format_linkedin_job_no_recipient = format_linkedin_job_draft


def format_linkedin_email_success(job: LinkedInJob) -> str:
    """Plain-text Telegram message for a sent LinkedIn application email."""
    score = f"{job.relevance_score}%" if job.relevance_score is not None else "—"
    lines = [
        "✅ ایمیل لینکدین ارسال شد",
        _DIVIDER,
        f"سمت: {_truncate(job.title or 'بدون عنوان', 200)}",
        f"شرکت: {_truncate(job.company or '—', 120)}",
        f"مکان: {_truncate(job.location or '—', 120)}",
        f"تطابق رزومه: {score}",
        f"به: {_truncate(job.recipient_email or '—', 120)}",
        f"موضوع: {_truncate(job.email_subject or '—', 200)}",
    ]
    if job.job_url:
        lines.append(f"آگهی: {job.job_url.strip()}")
    body = _truncate(job.email_body or "", MAX_PROPOSAL)
    if body:
        lines.extend(["", "متن:", body])
    return "\n".join(lines)
