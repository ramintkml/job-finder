"""Inspect ATS / work queue state on VPS."""

from app.database import AtsResume, LinkedInJob, SessionLocal, WorkJob

db = SessionLocal()
try:
    print("=== work jobs ===")
    for row in db.query(WorkJob).order_by(WorkJob.id.desc()).limit(10):
        print(
            f"job#{row.id} type={row.job_type} status={row.status} "
            f"entity={row.entity_id} err={row.error_message!r} "
            f"claimed_by={row.claimed_by} claimed_at={row.claimed_at}"
        )
    print("=== ats ===")
    for a in db.query(AtsResume).order_by(AtsResume.id.desc()).limit(8):
        print(
            f"ats#{a.id} li_job={a.linkedin_job_db_id} status={a.status} "
            f"score={a.total_score} err={a.error_message!r} docx={a.docx_path!r}"
        )
    print("=== linkedin ===")
    for j in db.query(LinkedInJob).order_by(LinkedInJob.id.desc()).limit(8):
        print(f"li#{j.id} status={j.status} title={(j.title or '')[:60]!r}")
finally:
    db.close()
