import json
import re
from dataclasses import dataclass

from app.config import GUIDE_PATH, settings


@dataclass
class ScreeningResult:
    action: str  # bid | skip
    confidence: int
    skip_reason: str | None
    review_reason: str | None
    is_hourly: bool
    currency: str


@dataclass
class ProposalResult:
    proposal: str
    amount: float
    duration: int
    duration_type: str  # days | hours_per_week
    currency: str


def load_guide() -> str:
    if not GUIDE_PATH.is_file():
        return ""
    return GUIDE_PATH.read_text(encoding="utf-8")


def save_guide(content: str) -> None:
    GUIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
    GUIDE_PATH.write_text(content or "", encoding="utf-8")


def _load_screening_context(guide: str) -> str:
    """Compact rules for screening — avoids sending the full proposal guide (~2k+ tokens)."""
    parts: list[str] = []

    who_start = guide.find("## Who You Are")
    who_end = guide.find("## Proposal Rules")
    if who_start >= 0 and who_end > who_start:
        parts.append(guide[who_start:who_end].strip())

    filter_start = guide.find("## Project Filtering")
    filter_end = guide.find("## Freelancer.com Platform Rules")
    if filter_start >= 0 and filter_end > filter_start:
        parts.append(guide[filter_start:filter_end].strip())

    step_start = guide.find("### Step 1 — Screening")
    step_end = guide.find("### Step 2 — Full bid")
    if step_start >= 0 and step_end > step_start:
        parts.append(guide[step_start:step_end].strip())

    if parts:
        return "\n\n".join(parts)

    return (
        "Skip non-English projects. Skip data entry, vague scope, unfair terms, "
        "suspiciously low budgets. Bid on AI, Python, automation, ML, full-stack work."
    )


def _truncate_project_text(text: str, limit: int = 3500) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _extract_json(text: str) -> dict:
    if not text or not text.strip():
        raise ValueError("Empty AI response")

    raw = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fence:
        raw = fence.group(1).strip()

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        preview = raw[:400].replace("\n", " ")
        raise ValueError(f"No JSON object found in AI response. Preview: {preview}")

    try:
        return json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        preview = raw[start : min(start + 400, end + 1)].replace("\n", " ")
        raise ValueError(f"Invalid JSON in AI response: {exc}. Preview: {preview}") from exc


SCREENING_JSON_INSTRUCTION = (
    'Return exactly one JSON object with keys: action, confidence, skip_reason, '
    'review_reason, is_hourly, currency. Example: '
    '{"action":"bid","confidence":85,"skip_reason":null,"review_reason":"Good fit",'
    '"is_hourly":false,"currency":"USD"}'
)

PROPOSAL_JSON_INSTRUCTION = (
    'Return exactly one JSON object with keys: proposal, amount, duration, '
    'duration_type, currency, is_hourly. The proposal value must use \\n\\n between paragraphs.'
)


def _call_anthropic(system: str, user: str, *, model: str, max_tokens: int = 2048) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return message.content[0].text


def _normalize_model(provider: str, model: str) -> str:
    p = provider.lower().strip()
    if p == "gemini":
        aliases = {
            "gemini-2.0-flash": "gemini-2.5-flash",
            "gemini-2.0-flash-lite": "gemini-2.5-flash-lite",
            "gemini-1.5-flash": "gemini-2.5-flash",
            "gemini-1.5-flash-latest": "gemini-2.5-flash",
            "gemini-1.5-pro": "gemini-2.5-pro",
            "gemini-1.5-pro-latest": "gemini-2.5-pro",
        }
        return aliases.get(model, model)
    return model


def _call_openai_compatible(
    system: str,
    user: str,
    *,
    api_key: str,
    model: str,
    provider: str = "",
    base_url: str | None = None,
    max_tokens: int = 2048,
    json_mode: bool = False,
) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url)
    model = _normalize_model(provider, model)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    create_kwargs: dict = {"model": model, "messages": messages}
    if provider.lower().strip() == "gemini":
        create_kwargs["temperature"] = 0
    if json_mode:
        create_kwargs["response_format"] = {"type": "json_object"}

    errors: list[str] = []
    for token_key in ("max_tokens", "max_completion_tokens"):
        try:
            response = client.chat.completions.create(**create_kwargs, **{token_key: max_tokens})
            choice = response.choices[0]
            content = (choice.message.content or "").strip()
            if not content:
                finish = getattr(choice, "finish_reason", "unknown")
                raise ValueError(f"Empty AI response (finish_reason={finish})")
            return content
        except Exception as exc:
            errors.append(f"{token_key}: {exc}")
            message = str(exc).lower()
            if token_key == "max_tokens" and (
                "max_tokens" in message or "unsupported" in message or "not supported" in message
            ):
                continue
            if json_mode and "response_format" in message and "response_format" in create_kwargs:
                create_kwargs.pop("response_format", None)
                create_kwargs["messages"] = [
                    {
                        "role": "system",
                        "content": (
                            f"{system} Output ONLY a single valid JSON object. "
                            "No markdown fences, no explanation, no other text."
                        ),
                    },
                    {"role": "user", "content": user},
                ]
                continue
            raise
    raise RuntimeError(" | ".join(errors))


def _resolve_provider_call(provider: str) -> tuple[str, str | None]:
    p = provider.lower().strip()
    if p == "openai":
        if not settings.openai_api_key:
            raise ValueError("OpenAI API key is not configured")
        return settings.openai_api_key, None
    if p == "deepseek":
        if not settings.deepseek_api_key:
            raise ValueError("DeepSeek API key is not configured")
        return settings.deepseek_api_key, "https://api.deepseek.com"
    if p == "groq":
        if not settings.groq_api_key:
            raise ValueError(
                "Groq API key is not configured. Set GROQ_API_KEY in backend/.env "
                "or save it in Settings → General."
            )
        return settings.groq_api_key, "https://api.groq.com/openai/v1"
    if p == "gemini":
        if not settings.gemini_api_key:
            raise ValueError("Gemini API key is not configured")
        return settings.gemini_api_key, "https://generativelanguage.googleapis.com/v1beta/openai/"
    if p == "anthropic":
        if not settings.anthropic_api_key:
            raise ValueError("Anthropic API key is not configured")
        return "", None
    raise ValueError(
        f"Unknown AI provider '{provider}'. Use groq, gemini, deepseek, anthropic, or openai."
    )


async def _call_ai(
    system: str,
    user: str,
    *,
    provider: str,
    model: str,
    max_tokens: int = 2048,
) -> str:
    api_key, base_url = _resolve_provider_call(provider)
    if provider.lower().strip() == "anthropic":
        return _call_anthropic(system, user, model=model, max_tokens=max_tokens)
    return _call_openai_compatible(
        system,
        user,
        api_key=api_key,
        model=model,
        provider=provider,
        base_url=base_url,
        max_tokens=max_tokens,
        json_mode=True,
    )


def _detect_hourly(text: str) -> bool:
    lower = text.lower()
    return "hourly" in lower or "per hour" in lower or "/hr" in lower


def _detect_currency(text: str) -> str:
    lower = text.lower()
    if "eur" in lower or "€" in text:
        return "EUR"
    if "gbp" in lower or "£" in text:
        return "GBP"
    return "USD"


def _confidence_from_json(data: dict, default: int = 0) -> int:
    """Parse 0–100 confidence from AI JSON; handles null/missing/invalid values."""
    try:
        return max(0, min(100, int(data.get("confidence") or default)))
    except (TypeError, ValueError):
        return default


def _parse_screening_data(data: dict, project_text: str) -> ScreeningResult:
    action = str(data.get("action") or "skip").lower().strip()
    if action not in ("bid", "skip"):
        action = "skip"
    confidence = _confidence_from_json(data)
    skip_reason = data.get("skip_reason")
    review_reason = data.get("review_reason")
    is_hourly = bool(data.get("is_hourly", _detect_hourly(project_text)))
    currency = str(data.get("currency") or _detect_currency(project_text))

    if action == "skip":
        return ScreeningResult(
            action="skip",
            confidence=confidence,
            skip_reason=str(skip_reason).strip() if skip_reason else "AI screening declined",
            review_reason=None,
            is_hourly=is_hourly,
            currency=currency,
        )

    return ScreeningResult(
        action="bid",
        confidence=confidence,
        skip_reason=None,
        review_reason=str(review_reason).strip() if review_reason else None,
        is_hourly=is_hourly,
        currency=currency,
    )


async def ai_screen_project(project_text: str, guide_override: str | None = None) -> ScreeningResult:
    """LLM screening against the full proposal guide (Step 1 — Screening)."""
    guide = guide_override or load_guide()
    system = (
        "You are a freelancer project screening assistant. "
        "Follow the proposal guide exactly — especially Project Filtering and "
        "Step 1 — Screening. Decide skip vs bid and score confidence 0–100. "
        "Do not write a proposal. "
        "Respond with valid JSON only — no markdown fences, no extra text."
    )
    user = (
        f"{guide}\n\n---\n\n"
        "Screen this project (Step 1 — Screening only):\n\n"
        f"{_truncate_project_text(project_text, limit=5000)}\n\n"
        f"{SCREENING_JSON_INSTRUCTION}"
    )
    data = _extract_json(
        await _call_ai(
            system,
            user,
            provider=settings.screening_provider,
            model=settings.screening_model(),
            max_tokens=512,
        )
    )
    return _parse_screening_data(data, project_text)


async def screen_bot_project(project_text: str) -> ScreeningResult:
    """
    @KayaProjectsBot flow: vector pre-filter (≥65%), then Groq/LLM review with full guide.
    Auto-bid when AI confidence ≥ auto_bid_confidence_threshold (default 85%).
    """
    from app.rag.matcher import vector_screen_project_async

    vector = await vector_screen_project_async(project_text)
    if vector.action == "skip":
        return vector

    ai = await ai_screen_project(project_text)
    if ai.action == "skip":
        if vector.confidence:
            ai.skip_reason = (
                f"{ai.skip_reason or 'AI screening declined'} "
                f"(vector pre-match {vector.confidence}%)"
            ).strip()
        return ai

    if not ai.review_reason:
        ai.review_reason = f"AI match {ai.confidence}%"
    if vector.confidence:
        ai.review_reason = f"{ai.review_reason} (vector {vector.confidence}%)"
    return ai


async def screen_project(project_text: str, guide_override: str | None = None) -> ScreeningResult:
    """Freelancer API flow — vector match only (PC chroma when VPS is lean)."""
    from app.rag.matcher import vector_screen_project_async

    return await vector_screen_project_async(project_text)


async def generate_proposal(project_text: str, guide_override: str | None = None) -> ProposalResult:
    """Write a full proposal with bid amount and duration.

    Bid amount is always 15% below the budget range average when a budget can be parsed
    (bot and API flows). The LLM must use that same amount in the proposal text.
    """
    from app.filters.budget_parse import compute_bid_amount, parse_budget_from_text

    guide = guide_override or load_guide()
    parsed_budget = parse_budget_from_text(project_text)
    target_amount = compute_bid_amount(parsed_budget, discount=0.15)
    currency_hint = parsed_budget.currency or "USD"

    amount_rule = (
        f"You MUST set JSON \"amount\" to exactly {target_amount} {currency_hint} "
        f"(15% below the budget range average). Mention this same number in the proposal if you cite a price."
        if target_amount is not None
        else (
            "Read the budget line and set amount to 15% below the range average "
            "(e.g. $250-$750 → average 500 → bid 425)."
        )
    )
    system = (
        "You are a freelancer bidding assistant. Follow the guide exactly. "
        "Write a tailored proposal with bid amount and duration. "
        f"{amount_rule} "
        "The proposal string must use \\n\\n between paragraphs. "
        "Respond with valid JSON only — no markdown fences, no extra text."
    )
    user = (
        f"{guide}\n\n---\n\n"
        "Write a full bid for this project (proposal mode):\n\n"
        f"{_truncate_project_text(project_text, limit=5000)}\n\n"
        f"{PROPOSAL_JSON_INSTRUCTION}"
    )
    data = _extract_json(
        await _call_ai(
            system,
            user,
            provider=settings.proposal_provider,
            model=settings.proposal_model(),
            max_tokens=1024,
        )
    )
    if not data.get("proposal"):
        raise ValueError("AI did not return a proposal")
    proposal_text = str(data["proposal"]).replace("\\n", "\n").strip()

    llm_amount = float(data["amount"]) if data.get("amount") is not None else 0
    amount = target_amount if target_amount is not None else llm_amount
    currency = parsed_budget.currency or data.get("currency", "USD")

    return ProposalResult(
        proposal=proposal_text,
        amount=amount,
        duration=int(data["duration"]) if data.get("duration") is not None else 7,
        duration_type=data.get("duration_type", "days"),
        currency=currency,
    )


# Kept for backwards compatibility if referenced elsewhere
async def evaluate_project(project_text: str, guide_override: str | None = None) -> ScreeningResult:
    return await screen_project(project_text, guide_override)
