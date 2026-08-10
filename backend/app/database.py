from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DB_PATH

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    freelancer_project_id = Column(String(32), unique=True, nullable=True, index=True)
    telegram_message_id = Column(Integer, nullable=True)
    title = Column(String(512), default="")
    description = Column(Text, default="")
    raw_message = Column(Text, default="")
    budget_text = Column(String(256), default="")
    is_hourly = Column(Boolean, default=False)
    currency = Column(String(16), default="USD")

    status = Column(String(32), default="new", index=True)
    # new | skipped | pending_review | queued | bidding | submitted | failed

    skip_reason = Column(Text, nullable=True)
    review_reason = Column(Text, nullable=True)
    confidence = Column(Integer, nullable=True)
    proposal = Column(Text, nullable=True)
    bid_amount = Column(Float, nullable=True)
    bid_duration = Column(Integer, nullable=True)
    duration_type = Column(String(32), nullable=True)  # days | hours_per_week

    auto_bid = Column(Boolean, default=False)
    error_message = Column(Text, nullable=True)
    review_channel_message_id = Column(Integer, nullable=True)
    review_channel_chat_id = Column(Integer, nullable=True)
    review_notified_at = Column(DateTime, nullable=True)
    source = Column(String(32), default="telegram_bot", index=True)
    # telegram_bot | freelancer_api

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    submitted_at = Column(DateTime, nullable=True)


class AppSettings(Base):
    __tablename__ = "app_settings"

    key = Column(String(64), primary_key=True)
    value = Column(Text, default="")


class User(Base):
    """Telegram end-user of LinkedIn Job Finder."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id = Column(Integer, unique=True, nullable=False, index=True)
    chat_id = Column(Integer, nullable=False, index=True)
    username = Column(String(128), nullable=True)
    first_name = Column(String(128), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class Subscription(Base):
    """Paid plan order — pending until admin confirms card-to-card receipt."""

    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    months = Column(Integer, nullable=False)  # 1 | 3 | 6 | 12
    include_ai = Column(Boolean, default=False)
    include_ats = Column(Boolean, default=False)
    base_price = Column(Float, default=0.0)
    ai_price = Column(Float, default=0.0)
    ats_price = Column(Float, default=0.0)
    total_price = Column(Float, default=0.0)
    currency = Column(String(8), default="USD")
    payment_method = Column(String(32), default="card_to_card")
    status = Column(String(32), default="pending", index=True)
    # pending | awaiting_confirm | active | expired | cancelled
    receipt_file_id = Column(String(256), nullable=True)
    receipt_received_at = Column(DateTime, nullable=True)
    activated_by = Column(String(64), nullable=True)
    started_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class DailyBidCount(Base):
    __tablename__ = "daily_bid_counts"

    date = Column(String(10), primary_key=True)  # YYYY-MM-DD UTC
    count = Column(Integer, default=0)


class LinkedInJob(Base):
    __tablename__ = "linkedin_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    linkedin_job_id = Column(String(32), unique=True, nullable=False, index=True)
    title = Column(String(512), default="")
    company = Column(String(256), default="")
    location = Column(String(256), default="")
    job_url = Column(String(1024), default="")
    description = Column(Text, default="")
    search_phrase = Column(String(256), default="")
    status = Column(String(32), default="found", index=True)
    # found | matched | emailed | draft | skipped | failed
    match_reason = Column(Text, nullable=True)
    email_subject = Column(String(512), nullable=True)
    email_body = Column(Text, nullable=True)
    recipient_email = Column(String(256), nullable=True)
    error_message = Column(Text, nullable=True)
    relevance_score = Column(Integer, nullable=True)
    review_channel_message_id = Column(Integer, nullable=True)
    review_channel_chat_id = Column(Integer, nullable=True)
    review_notified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    emailed_at = Column(DateTime, nullable=True)


class AtsResume(Base):
    __tablename__ = "ats_resumes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    linkedin_job_db_id = Column(Integer, unique=True, nullable=False, index=True)
    status = Column(String(32), default="pending", index=True)
    # pending | generating | ready | failed
    total_score = Column(Integer, nullable=True)
    scores_json = Column(Text, nullable=True)
    keyword_matched = Column(Text, nullable=True)
    keyword_missing = Column(Text, nullable=True)
    resume_json = Column(Text, nullable=True)
    docx_path = Column(String(1024), nullable=True)
    pdf_path = Column(String(1024), nullable=True)
    diff_summary = Column(Text, nullable=True)
    improvement_tips_json = Column(Text, nullable=True)
    channel_message_id = Column(Integer, nullable=True)
    channel_chat_id = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class BotApplication(Base):
    """Jobs pasted to Telegram /apply (Codex bridge) and their generated resumes."""

    __tablename__ = "bot_applications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id = Column(Integer, nullable=False, index=True)
    work_job_id = Column(Integer, nullable=True, index=True)
    title = Column(String(512), default="")
    company = Column(String(256), default="")
    job_url = Column(String(1024), default="")
    description = Column(Text, default="")
    fit_score = Column(Integer, nullable=True)
    recommendation = Column(String(64), nullable=True)
    summary = Column(Text, nullable=True)
    ats_notes = Column(Text, nullable=True)
    ats_score = Column(Integer, nullable=True)
    ats_scores_json = Column(Text, nullable=True)
    evaluation_md = Column(Text, nullable=True)
    resume_md = Column(Text, nullable=True)
    resume_json = Column(Text, nullable=True)
    resume_fa_json = Column(Text, nullable=True)
    resume_docx_path = Column(String(1024), nullable=True)
    resume_fa_docx_path = Column(String(1024), nullable=True)
    resume_pdf_path = Column(String(1024), nullable=True)
    resume_fa_pdf_path = Column(String(1024), nullable=True)
    evaluation_path = Column(String(1024), nullable=True)
    output_dir = Column(String(1024), nullable=True)
    status = Column(String(32), default="ready", index=True)
    # ready | improving | failed
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class WorkJob(Base):
    """Heavy work queue — VPS enqueues; PC worker claims and completes."""

    __tablename__ = "work_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_type = Column(String(64), nullable=False, index=True)
    # linkedin_create_email | linkedin_create_resume | ats_regenerate | project_send_bid
    entity_id = Column(Integer, nullable=False, index=True)
    status = Column(String(32), default="pending", index=True)
    # pending | claimed | done | failed | cancelled
    payload_json = Column(Text, nullable=True)
    result_json = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    claimed_by = Column(String(128), nullable=True)
    claimed_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


def init_db() -> None:
    DATA_DIR = DB_PATH.parent
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _migrate_columns()


def _migrate_columns() -> None:
    """Add new columns to existing SQLite databases."""
    with engine.connect() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(projects)").fetchall()
        columns = {row[1] for row in rows}
        if "review_reason" not in columns:
            conn.exec_driver_sql("ALTER TABLE projects ADD COLUMN review_reason TEXT")
            conn.commit()
        if "review_channel_message_id" not in columns:
            conn.exec_driver_sql("ALTER TABLE projects ADD COLUMN review_channel_message_id INTEGER")
            conn.commit()
        if "source" not in columns:
            conn.exec_driver_sql(
                "ALTER TABLE projects ADD COLUMN source VARCHAR(32) DEFAULT 'telegram_bot'"
            )
            conn.commit()
        if "review_channel_chat_id" not in columns:
            conn.exec_driver_sql("ALTER TABLE projects ADD COLUMN review_channel_chat_id INTEGER")
            conn.commit()
        if "review_notified_at" not in columns:
            conn.exec_driver_sql("ALTER TABLE projects ADD COLUMN review_notified_at DATETIME")
            conn.commit()
        conn.exec_driver_sql(
            """
            UPDATE projects
            SET review_notified_at = updated_at
            WHERE review_channel_message_id IS NOT NULL
              AND review_notified_at IS NULL
            """
        )
        conn.commit()
        li_rows = conn.exec_driver_sql("PRAGMA table_info(linkedin_jobs)").fetchall()
        li_columns = {row[1] for row in li_rows}
        if "relevance_score" not in li_columns:
            conn.exec_driver_sql("ALTER TABLE linkedin_jobs ADD COLUMN relevance_score INTEGER")
            conn.commit()
        if "review_channel_message_id" not in li_columns:
            conn.exec_driver_sql("ALTER TABLE linkedin_jobs ADD COLUMN review_channel_message_id INTEGER")
            conn.commit()
        if "review_channel_chat_id" not in li_columns:
            conn.exec_driver_sql("ALTER TABLE linkedin_jobs ADD COLUMN review_channel_chat_id INTEGER")
            conn.commit()
        if "review_notified_at" not in li_columns:
            conn.exec_driver_sql("ALTER TABLE linkedin_jobs ADD COLUMN review_notified_at DATETIME")
            conn.commit()
        ats_rows = conn.exec_driver_sql("PRAGMA table_info(ats_resumes)").fetchall()
        ats_columns = {row[1] for row in ats_rows} if ats_rows else set()
        if ats_columns and "improvement_tips_json" not in ats_columns:
            conn.exec_driver_sql("ALTER TABLE ats_resumes ADD COLUMN improvement_tips_json TEXT")
            conn.commit()

        bot_app_rows = conn.exec_driver_sql("PRAGMA table_info(bot_applications)").fetchall()
        bot_app_cols = {row[1] for row in bot_app_rows} if bot_app_rows else set()
        if bot_app_cols and "ats_scores_json" not in bot_app_cols:
            conn.exec_driver_sql("ALTER TABLE bot_applications ADD COLUMN ats_scores_json TEXT")
            conn.commit()
        for col, decl in (
            ("resume_json", "TEXT"),
            ("resume_fa_json", "TEXT"),
            ("resume_fa_docx_path", "VARCHAR(1024)"),
            ("resume_pdf_path", "VARCHAR(1024)"),
            ("resume_fa_pdf_path", "VARCHAR(1024)"),
        ):
            if bot_app_cols and col not in bot_app_cols:
                conn.exec_driver_sql(f"ALTER TABLE bot_applications ADD COLUMN {col} {decl}")
                conn.commit()

        sub_rows = conn.exec_driver_sql("PRAGMA table_info(subscriptions)").fetchall()
        sub_columns = {row[1] for row in sub_rows} if sub_rows else set()
        if sub_columns:
            if "payment_method" not in sub_columns:
                conn.exec_driver_sql(
                    "ALTER TABLE subscriptions ADD COLUMN payment_method VARCHAR(32) DEFAULT 'card_to_card'"
                )
                conn.commit()
            if "receipt_file_id" not in sub_columns:
                conn.exec_driver_sql("ALTER TABLE subscriptions ADD COLUMN receipt_file_id VARCHAR(256)")
                conn.commit()
            if "receipt_received_at" not in sub_columns:
                conn.exec_driver_sql("ALTER TABLE subscriptions ADD COLUMN receipt_received_at DATETIME")
                conn.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
