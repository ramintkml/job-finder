from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
GUIDE_PATH = DATA_DIR / "proposal_guide.md"
CHROMA_PATH = DATA_DIR / "chroma"
DB_PATH = DATA_DIR / "freelancer.db"
SESSION_PATH = DATA_DIR / "telegram.session"
ATS_DIR = DATA_DIR / "ats"
ATS_GUIDE_PATH = Path(__file__).resolve().parent / "ats" / "ATS_Friendly_Resume_Guide.md"
CV_MD_PATH = DATA_DIR / "cv" / "Ramin_Takmil_CV.md"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / "backend" / ".env"),
        env_file_encoding="utf-8",
        # Empty process env (e.g. PM2) must not override values from .env
        env_ignore_empty=True,
        extra="ignore",
    )

    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_phone: str = ""
    telegram_bot_username: str = "KayaProjectsBot"
    telegram_channel_id: str = ""
    telegram_freelancer_channel_id: str = ""
    telegram_linkedin_channel_id: str = ""
    # Phase 1 review bot — multi-user; token required
    telegram_review_bot_token: str = ""
    # Optional admin chat for receipt notifications (private chat id)
    telegram_review_chat_id: str = ""
    # Comma-separated Telegram user ids who are admins (preferred)
    # Example: TELEGRAM_ADMIN_IDS=123456789
    telegram_admin_ids: str = ""

    ai_provider: str = "groq"
    ai_screening_provider: str = ""
    ai_proposal_provider: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    deepseek_api_key: str = ""
    groq_api_key: str = ""
    gemini_api_key: str = ""
    ai_model: str = ""
    ai_screening_model: str = ""
    ai_proposal_model: str = ""

    auto_bid_confidence_threshold: int = 85
    max_bids_per_day: int = 5
    test_mode: bool = True
    automation_enabled: bool = True
    freelancer_bidding_enabled: bool = False
    review_timeout_minutes: int = 15

    host: str = "127.0.0.1"
    port: int = 8000

    # Phase 2 — VPS queues heavy work; PC worker claims via WORKER_API_SECRET
    queue_heavy_work: bool = False
    worker_api_secret: str = ""
    # PC worker only — base URL of the VPS app (use tunnel: http://127.0.0.1:8000)
    worker_remote_url: str = "http://127.0.0.1:8000"
    worker_id: str = ""
    worker_poll_seconds: float = 3.0

    # Safety — RAM/CPU overload warnings to the review bot
    system_alerts_enabled: bool = True
    system_alert_cpu_percent: float = 85.0
    system_alert_ram_percent: float = 85.0
    system_alert_interval_seconds: int = 60
    system_alert_cooldown_seconds: int = 300

    freelancer_client_id: str = ""
    freelancer_client_secret: str = ""
    freelancer_redirect_uri: str = "http://127.0.0.1:8000/api/freelancer/callback"
    freelancer_sandbox: bool = True
    freelancer_advanced_scopes: str = "1"

    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    linkedin_redirect_uri: str = "http://127.0.0.1:8000/api/linkedin/callback"

    # Sellable plans (placeholders — set real prices in .env)
    plan_currency: str = "USD"
    plan_price_1_month: float = 9.99
    plan_price_3_month: float = 24.99
    plan_price_6_month: float = 44.99
    plan_price_12_month: float = 79.99
    # Add-ons billed as (monthly rate × plan months)
    plan_ai_addon_per_month: float = 4.99
    plan_ats_addon_per_month: float = 4.99

    # Card-to-card payment (shown to users after they order a plan)
    payment_card_number: str = ""
    payment_card_holder: str = ""
    payment_bank_name: str = ""
    payment_extra_note: str = ""

    @property
    def app_base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def freelancer_client_configured(self) -> bool:
        return bool(self.freelancer_client_id.strip() and self.freelancer_client_secret.strip())

    @property
    def linkedin_client_configured(self) -> bool:
        return bool(self.linkedin_client_id.strip() and self.linkedin_client_secret.strip())

    @property
    def screening_provider(self) -> str:
        return (self.ai_screening_provider or self.ai_provider).lower().strip()

    @property
    def proposal_provider(self) -> str:
        return (self.ai_proposal_provider or self.ai_provider).lower().strip()

    @staticmethod
    def default_model_for(provider: str) -> str:
        p = provider.lower().strip()
        if p == "openai":
            return "gpt-4o"
        if p == "deepseek":
            return "deepseek-chat"
        if p == "groq":
            return "llama-3.3-70b-versatile"
        if p == "gemini":
            return "gemini-2.5-flash"
        return "claude-sonnet-4-20250514"

    @staticmethod
    def default_screening_model_for(provider: str) -> str:
        p = provider.lower().strip()
        if p == "groq":
            return "llama-3.1-8b-instant"
        if p == "gemini":
            return "gemini-2.5-flash"
        return Settings.default_model_for(provider)

    def screening_model(self) -> str:
        return self.ai_screening_model or self.default_screening_model_for(self.screening_provider)

    def proposal_model(self) -> str:
        return self.ai_proposal_model or self.default_model_for(self.proposal_provider)

    @property
    def admin_telegram_ids(self) -> set[int]:
        """Telegram user ids allowed as admins."""
        ids: set[int] = set()
        for part in (self.telegram_admin_ids or "").replace(";", ",").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ids.add(int(part))
            except ValueError:
                continue
        # Private admin chat id is usually the same as the user's telegram id
        chat = (self.telegram_review_chat_id or "").strip().lstrip("-")
        if chat.isdigit():
            ids.add(int(chat))
        return ids

    @property
    def default_model(self) -> str:
        """Legacy — proposal model."""
        if self.ai_model:
            return self.ai_model
        return self.proposal_model()


settings = Settings()
