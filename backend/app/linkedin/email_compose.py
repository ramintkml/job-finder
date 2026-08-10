import json
import re

from app.ai.evaluator import _call_openai_compatible, _resolve_provider_call, load_guide
from app.config import settings
from app.linkedin.settings import DEFAULT_EMAIL_TEMPLATE, LinkedInSettings

SAMPLE_LINKEDIN_JOB = {
    "title": "Python Developer — AI Automation",
    "company": "TechFlow Solutions",
    "location": "Remote (contract)",
    "job_url": "https://www.linkedin.com/jobs/view/sample-python-ai-automation",
    "description": """We are hiring a Python developer to build internal automation tools and integrate LLMs into our product workflow.

Requirements:
- Strong Python (FastAPI, scripting, ETL/data pipelines)
- Experience integrating OpenAI or similar LLM APIs into business tools
- Ability to deliver full-stack features and reliable REST integrations
- Bonus: machine learning, computer vision, or workflow automation background

This is a remote contract role with potential to extend. The team values clear communication and independent delivery.""",
}

_BRIEF_JOB_CHARS = 480
_PROFILE_CHARS = 400
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

_BLOCKED_EMAIL_FRAGMENTS = (
    "noreply",
    "no-reply",
    "donotreply",
    "linkedin.com",
    "example.com",
    "sentry.io",
    "wixpress.com",
)

_PLACEHOLDER_RE = re.compile(r"\[([^\]]+)\]")


def _extract_json(text: str) -> dict:
    raw = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fence:
        raw = fence.group(1).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("AI did not return JSON for email")
    return json.loads(raw[start : end + 1])


def _call_ai(system: str, user: str) -> str:
    provider = settings.proposal_provider
    api_key, base_url = _resolve_provider_call(provider)
    model = settings.proposal_model()
    return _call_openai_compatible(
        system,
        user,
        api_key=api_key,
        model=model,
        provider=provider,
        base_url=base_url,
        max_tokens=768,
        json_mode=True,
    )


def _template_placeholders(template: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for match in _PLACEHOLDER_RE.finditer(template):
        key = match.group(1).strip()
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _applicant_emails(cfg: LinkedInSettings) -> set[str]:
    emails: set[str] = set()
    for value in (cfg.gmail_address, cfg.from_email, cfg.linkedin_email, cfg.notification_email):
        cleaned = (value or "").strip().lower()
        if cleaned:
            emails.add(cleaned)
    return emails


def _is_blocked_recipient(email: str) -> bool:
    lower = email.strip().lower()
    if not lower or "@" not in lower:
        return True
    return any(fragment in lower for fragment in _BLOCKED_EMAIL_FRAGMENTS)


def _extract_emails_from_text(text: str, *, exclude: set[str]) -> list[str]:
    seen: set[str] = set()
    found: list[str] = []
    for match in _EMAIL_RE.findall(text or ""):
        candidate = match.strip()
        lower = candidate.lower()
        if lower in seen or lower in exclude or _is_blocked_recipient(candidate):
            continue
        seen.add(lower)
        found.append(candidate)
    return found


def resolve_recruiter_email(
    job: dict,
    cfg: LinkedInSettings,
    ai_guess: str = "",
) -> str:
    """Pick a hiring contact email from the job posting — never the applicant's own address."""
    exclude = _applicant_emails(cfg)
    description = str(job.get("description") or "")
    blob = "\n".join(
        [
            str(job.get("title") or ""),
            str(job.get("company") or ""),
            str(job.get("location") or ""),
            description,
        ]
    )

    for candidate in (
        [ai_guess.strip()] if ai_guess.strip() else []
    ):
        if candidate.lower() not in exclude and not _is_blocked_recipient(candidate):
            return candidate

    for candidate in _extract_emails_from_text(blob, exclude=exclude):
        return candidate

    default = (cfg.default_recipient_email or "").strip()
    if default and default.lower() not in exclude and not _is_blocked_recipient(default):
        return default

    return ""


def _brief_job_summary(job: dict) -> str:
    title = str(job.get("title") or "").strip()
    company = str(job.get("company") or "").strip()
    location = str(job.get("location") or "").strip()
    description = re.sub(r"\s+", " ", str(job.get("description") or "").strip())
    if len(description) > _BRIEF_JOB_CHARS:
        description = description[: _BRIEF_JOB_CHARS - 1].rsplit(" ", 1)[0] + "…"
    lines = [f"Title: {title or 'n/a'}", f"Company: {company or 'n/a'}"]
    if location:
        lines.append(f"Location: {location}")
    if description:
        lines.append(f"Summary: {description}")
    return "\n".join(lines)


def _brief_applicant_profile(cfg: LinkedInSettings) -> str:
    guide_excerpt = ""
    try:
        guide = load_guide()
        who = guide.find("## Who You Are")
        rules = guide.find("## Proposal Rules")
        if who >= 0 and rules > who:
            guide_excerpt = guide[who:rules].strip()[:_PROFILE_CHARS]
    except OSError:
        pass

    parts = [
        f"Name: {cfg.applicant_name or 'n/a'}",
        f"Role: {cfg.applicant_role or 'n/a'}",
        f"Top skills: {cfg.top_skills or 'n/a'}",
    ]
    exp = (cfg.experience_summary or guide_excerpt or "").strip()
    if exp:
        if len(exp) > _PROFILE_CHARS:
            exp = exp[: _PROFILE_CHARS - 1].rsplit(" ", 1)[0] + "…"
        parts.append(f"Experience: {exp}")
    return "\n".join(parts)


def _static_placeholder_value(key: str, job: dict, cfg: LinkedInSettings) -> str | None:
    normalized = key.strip().lower()
    static = {
        "your name": (cfg.applicant_name or "").strip(),
        "your role": (cfg.applicant_role or "").strip(),
        "company name": str(job.get("company") or "").strip(),
        "position title": str(job.get("title") or "").strip(),
    }
    value = static.get(normalized)
    return value if value else None


def _ai_fill_placeholders(
    job: dict,
    cfg: LinkedInSettings,
    template: str,
) -> tuple[dict[str, str], str]:
    """Ask AI only for personalized placeholder values. Returns (fills, recipient_email)."""
    placeholders = _template_placeholders(template)
    ai_keys = [p for p in placeholders if _static_placeholder_value(p, job, cfg) is None]
    if not ai_keys:
        return {}, ""

    keys_block = "\n".join(f"- [{k}]" for k in ai_keys)
    system = (
        "You help fill job application email templates. "
        "Return JSON only: {\"recipient_email\": \"\", \"fills\": {\"Placeholder Name\": \"value\"}}. "
        "fills keys must match the placeholder names exactly (without brackets). "
        "Do NOT write the full email, subject, or body. "
        "Only return short text for each placeholder (one phrase or one sentence unless the placeholder implies more). "
        "For [Name], use a polite greeting name such as 'there' if the hiring contact is unknown. "
        "recipient_email must be empty unless a clear hiring or recruiter email appears in the job brief. "
        "Never use the applicant's own email."
    )
    user = f"""Applicant (brief):
{_brief_applicant_profile(cfg)}

Job (brief):
{_brief_job_summary(job)}

Placeholders to fill:
{keys_block}
"""
    raw = _call_ai(system, user)
    data = _extract_json(raw)
    recipient = str(data.get("recipient_email") or "").strip()
    fills_raw = data.get("fills") or {}
    if not isinstance(fills_raw, dict):
        raise ValueError("AI response missing fills object")

    fills: dict[str, str] = {}
    for key in ai_keys:
        if key in fills_raw and str(fills_raw[key]).strip():
            fills[key] = str(fills_raw[key]).strip()
        else:
            for fk, fv in fills_raw.items():
                if str(fk).strip().lower() == key.lower() and str(fv).strip():
                    fills[key] = str(fv).strip()
                    break
    return fills, recipient


def _apply_template(template: str, fills: dict[str, str]) -> str:
    text = template
    for key, value in fills.items():
        text = text.replace(f"[{key}]", value)
    return text


def _split_subject_body(composed: str, job: dict, cfg: LinkedInSettings) -> tuple[str, str]:
    lines = composed.strip().splitlines()
    if lines and lines[0].lower().startswith("subject:"):
        subject = lines[0].split(":", 1)[1].strip()
        body = "\n".join(lines[1:]).strip()
        return subject, body

    role = cfg.applicant_role or "Applicant"
    company = str(job.get("company") or "your company").strip()
    title = str(job.get("title") or "Role").strip()
    return f"Application — {title}", composed.strip()


def _assemble_email(
    template: str,
    job: dict,
    cfg: LinkedInSettings,
    ai_fills: dict[str, str],
) -> tuple[str, str]:
    placeholders = _template_placeholders(template)
    all_fills: dict[str, str] = {}

    for key in placeholders:
        static = _static_placeholder_value(key, job, cfg)
        if static:
            all_fills[key] = static
        elif key in ai_fills:
            all_fills[key] = ai_fills[key]
        else:
            all_fills[key] = f"[{key}]"

    composed = _apply_template(template, all_fills)
    return _split_subject_body(composed, job, cfg)


def compose_application_email(
    job: dict,
    cfg: LinkedInSettings,
) -> tuple[str, str, str]:
    """Return (subject, body, recipient_email). Skips applicant email — recruiter only."""
    template = cfg.email_template.strip() or DEFAULT_EMAIL_TEMPLATE
    ai_fills, ai_recipient = _ai_fill_placeholders(job, cfg, template)
    subject, body = _assemble_email(template, job, cfg, ai_fills)
    recipient = resolve_recruiter_email(job, cfg, ai_guess=ai_recipient)
    return subject, body, recipient


def compose_sample_application_email(cfg: LinkedInSettings) -> tuple[str, str, str]:
    """AI-fill placeholder values using sample LinkedIn job details."""
    return compose_application_email(SAMPLE_LINKEDIN_JOB, cfg)
