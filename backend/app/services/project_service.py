import re

from sqlalchemy.orm import Session

from app.ai.evaluator import ProposalResult, ScreeningResult
from app.database import Project

SOURCE_TELEGRAM_BOT = "telegram_bot"
SOURCE_FREELANCER_API = "freelancer_api"


def _extract_title(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[0][:512] if lines else "Untitled project"


def _extract_budget(text: str) -> str:
    patterns = [
        r"(?:fixed|hourly):\s*\$?\s*[\d,]+(?:\s*-\s*[\d,]+)?\s*USD",
        r"budget[:\s]+([^\n]+)",
        r"\$[\d,]+(?:\s*-\s*\$[\d,]+)?",
        r"USD\s*[\d,]+",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group(0)[:256]
            return re.sub(r"^budget:\s*", "", value, flags=re.IGNORECASE).strip()
    return ""


def _format_proposal_text(text: str) -> str:
    """Normalize proposal text for Telegram — preserve paragraph breaks."""
    text = text.strip().replace("\\n", "\n")
    if "\n\n" in text:
        return text
    # Split long single-paragraph proposals into two paragraphs at a sensible break.
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if len(sentences) >= 4:
        mid = max(2, len(sentences) // 2)
        return " ".join(sentences[:mid]).strip() + "\n\n" + " ".join(sentences[mid:]).strip()
    return text


def _detect_hourly(text: str) -> bool:
    lower = text.lower()
    return "hourly" in lower or "per hour" in lower or "/hr" in lower


def create_project_from_message(
    db: Session,
    text: str,
    message_id: int,
    freelancer_project_id: str | None,
    source: str = SOURCE_TELEGRAM_BOT,
) -> Project:
    if freelancer_project_id:
        existing = (
            db.query(Project)
            .filter_by(freelancer_project_id=str(freelancer_project_id))
            .first()
        )
        if existing:
            return existing

    project = Project(
        freelancer_project_id=freelancer_project_id,
        telegram_message_id=message_id,
        title=_extract_title(text),
        description=text,
        raw_message=text,
        budget_text=_extract_budget(text),
        is_hourly=_detect_hourly(text),
        status="new",
        source=source,
    )
    db.add(project)
    try:
        db.commit()
    except Exception:
        db.rollback()
        if freelancer_project_id:
            existing = (
                db.query(Project)
                .filter_by(freelancer_project_id=str(freelancer_project_id))
                .first()
            )
            if existing:
                return existing
        raise
    db.refresh(project)
    return project


def apply_screening(
    db: Session,
    project: Project,
    screening: ScreeningResult,
    auto_threshold: int,
) -> None:
    """Apply screening result — no proposal yet unless auto-bid threshold met."""
    project.confidence = screening.confidence
    project.is_hourly = screening.is_hourly
    project.currency = screening.currency
    project.proposal = None
    project.bid_amount = None
    project.bid_duration = None
    project.duration_type = None

    if screening.action == "skip":
        project.status = "skipped"
        project.skip_reason = screening.skip_reason
        project.review_reason = None
        project.auto_bid = False
        db.commit()
        return

    project.skip_reason = None
    project.review_reason = screening.review_reason

    if screening.confidence >= auto_threshold:
        project.status = "generating"
        project.auto_bid = True
    else:
        project.status = "pending_review"
        project.auto_bid = False

    db.commit()


def apply_proposal_for_telegram(db: Session, project: Project, proposal: ProposalResult) -> None:
    """Telegram bot flow — queue bid via @KayaProjectsBot button automation."""
    from app.config import settings

    project.proposal = _format_proposal_text(proposal.proposal)
    project.bid_amount = proposal.amount
    project.bid_duration = proposal.duration
    project.duration_type = proposal.duration_type
    project.currency = proposal.currency
    project.status = "test_ready" if settings.test_mode else "queued"
    db.commit()


def apply_proposal_for_api(db: Session, project: Project, proposal: ProposalResult) -> None:
    """Freelancer API flow — proposal ready for immediate API submit after channel send."""
    project.proposal = _format_proposal_text(proposal.proposal)
    project.bid_amount = proposal.amount
    project.bid_duration = proposal.duration
    project.duration_type = proposal.duration_type
    project.currency = proposal.currency
    # Stay on generating until submit_bid_for_project advances to bidding
    # (do not reset to pending_review — that would leave a half-ready review state).
    project.status = "generating"
    project.auto_bid = False
    db.commit()


def apply_proposal(db: Session, project: Project, proposal: ProposalResult) -> None:
    """Route proposal application based on project source."""
    source = project.source or SOURCE_TELEGRAM_BOT
    if source == SOURCE_FREELANCER_API:
        apply_proposal_for_api(db, project, proposal)
    else:
        apply_proposal_for_telegram(db, project, proposal)


async def approve_project_for_bid(db: Session, project: Project) -> None:
    """Generate proposal for a pending_review project and mark it ready to bid."""
    from app.ai.evaluator import generate_proposal

    project.status = "generating"
    db.commit()
    proposal = await generate_proposal(project.description)
    apply_proposal(db, project, proposal)


def skip_project_review(db: Session, project: Project, reason: str = "Manually skipped") -> None:
    """Decline a pending_review project."""
    project.status = "skipped"
    project.skip_reason = reason
    db.commit()
