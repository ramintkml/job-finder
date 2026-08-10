import json
from dataclasses import asdict, dataclass, field, fields

from sqlalchemy.orm import Session

from app.database import AppSettings

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
    return LinkedInSettings(
        search_phrases=["python automation", "machine learning engineer"],
        trigger_phrases=["python", "automation", "remote"],
        email_template=DEFAULT_EMAIL_TEMPLATE,
        applicant_name="Ramin Takmil",
        applicant_role="AI Specialist / Full-Stack Developer",
        top_skills="Python, AI/LLM integration, automation, full-stack development, computer vision",
        experience_summary=(
            "MSc Biomedical Engineering graduate building AI-powered products, automation systems, "
            "and full-stack apps for startups and product teams."
        ),
        from_name="Ramin Takmil",
        cv_file_path="data/cv/Ramin_Takmil_CV.pdf",
    )


def load_linkedin_settings(db: Session) -> LinkedInSettings:
    from app.linkedin.profile_sync import apply_linkedin_identity

    row = db.get(AppSettings, SETTINGS_KEY)
    if not row or not row.value:
        cfg = default_settings()
    else:
        try:
            data = json.loads(row.value)
            base = asdict(default_settings())
            base.update(data)
            valid = {f.name for f in fields(LinkedInSettings)}
            filtered = {k: v for k, v in base.items() if k in valid}
            cfg = LinkedInSettings(**filtered)
        except (json.JSONDecodeError, TypeError):
            cfg = default_settings()

    return apply_linkedin_identity(db, cfg)


def save_linkedin_settings(db: Session, settings: LinkedInSettings) -> None:
    row = db.get(AppSettings, SETTINGS_KEY)
    payload = json.dumps(asdict(settings))
    if row:
        row.value = payload
    else:
        db.add(AppSettings(key=SETTINGS_KEY, value=payload))
    db.commit()
