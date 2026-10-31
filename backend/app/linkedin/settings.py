import json
from dataclasses import asdict, dataclass, field, fields

from sqlalchemy.orm import Session

from app.database import AppSettings
from app.services.credentials import seal, unseal

SETTINGS_KEY = "linkedin_settings"


@dataclass
class LinkedInSettings:
    enabled: bool = False
    search_phrases: list[str] = field(default_factory=list)
    trigger_phrases: list[str] = field(default_factory=list)
    location: str = ""
    poll_interval_minutes: int = 60
    max_emails_per_day: int = 10
    test_mode: bool = True
    auto_mailing_enabled: bool = False
    list_cv_match_threshold: int = 65
    email_cv_match_threshold: int = 70
    ats_resume_threshold: int = 75

    applicant_name: str = ""
    applicant_role: str = ""
    linkedin_email: str = ""
    top_skills: str = ""
    experience_summary: str = ""
    cv_text: str = ""
    cv_file_path: str = ""

    gmail_address: str = ""
    gmail_app_password: str = ""
    from_email: str = ""
    from_name: str = ""
    notification_email: str = ""
    default_recipient_email: str = ""

    email_template: str = ""


DEFAULT_EMAIL_TEMPLATE = """Subject: Experienced [Your Role] – Interested in [Company Name]

Hi [Name],

I hope you're doing well. I recently came across the open [Position Title] role at [Company Name] on LinkedIn, and I'm excited about the opportunity to contribute my skills and experience to your team.

With a background in [your top 2–3 relevant skills or achievements], I have delivered [brief example of an impact/result]. I believe my expertise in [specific tools/technologies] and my passion for [something relevant to their mission/product] align closely with the role's requirements.

I would be happy to share more details about how I can add value to your team. Could we arrange a short call to discuss the position and my fit?

For your convenience, I've included my CV directly below, and also attached it as a PDF.

Thank you for your time, and I look forward to hearing from you.

Best regards,
[Your Name]"""


def default_settings() -> LinkedInSettings:
    return LinkedInSettings(email_template=DEFAULT_EMAIL_TEMPLATE)


def load_linkedin_settings(db: Session, user_id: int | None = None) -> LinkedInSettings:
    from app.linkedin.profile_sync import apply_linkedin_identity

    row = db.get(AppSettings, SETTINGS_KEY if user_id is None else f"linkedin_settings:{int(user_id)}")
    if not row or not row.value:
        cfg = default_settings()
    else:
        try:
            data = json.loads(row.value)
            stored_password = data.get("gmail_app_password") or ""
            data["gmail_app_password"] = unseal(stored_password)
            if stored_password and not stored_password.startswith("enc:v1:"):
                encrypted = dict(data, gmail_app_password=seal(stored_password))
                row.value = json.dumps(encrypted)
                db.commit()
            base = asdict(default_settings())
            base.update(data)
            valid = {f.name for f in fields(LinkedInSettings)}
            filtered = {k: v for k, v in base.items() if k in valid}
            cfg = LinkedInSettings(**filtered)
        except (json.JSONDecodeError, TypeError):
            cfg = default_settings()

    return apply_linkedin_identity(db, cfg) if user_id is None else cfg


def save_linkedin_settings(db: Session, settings: LinkedInSettings, user_id: int | None = None) -> None:
    row = db.get(AppSettings, SETTINGS_KEY if user_id is None else f"linkedin_settings:{int(user_id)}")
    data = asdict(settings)
    data["gmail_app_password"] = seal(data.get("gmail_app_password") or "")
    payload = json.dumps(data)
    if row:
        row.value = payload
    else:
        db.add(AppSettings(key=SETTINGS_KEY if user_id is None else f"linkedin_settings:{int(user_id)}", value=payload))
    db.commit()
