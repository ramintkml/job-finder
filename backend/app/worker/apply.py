"""Apply PC worker results back onto the VPS database and notify Telegram."""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import ATS_DIR
from app.database import AtsResume, BotApplication, LinkedInJob, Project, WorkJob
from app.worker.queue import (
    JOB_ATS_REGENERATE,
    JOB_CODEX_APPLY,
    JOB_LINKEDIN_EMAIL,
    JOB_LINKEDIN_RESUME,
    JOB_PROJECT_SEND,
    JOB_SAVE_FILES,
    JOB_VECTOR_SCREEN,
)

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_filename(name: str) -> str:
    import re

    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "Candidate").strip())
    return cleaned.strip("_") or "Candidate"


def _write_b64_file(path: Path, b64: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(b64))


def _normalize_recommendation(rec: str) -> str:
    raw = (rec or "").strip().lower()
    if "strong" in raw:
        return "Strong apply"
    if "skip" in raw or "no apply" in raw or "don't apply" in raw or "do not apply" in raw:
        return "Skip"
    if "conditional" in raw:
        return "Conditional"
    if "apply" in raw:
        return "Apply"
    return (rec or "—").strip() or "—"


def _fa_apply_verdict(rec: str, fit: int | None) -> tuple[str, str]:
    """Return (emoji_title, short_fa_line) for Telegram advice header."""
    norm = _normalize_recommendation(rec)
    if norm == "Strong apply":
        return "🟢 اپلای کنید (Strong)", "بر اساس CV شما، اپلای قوی توصیه می‌شود."
    if norm == "Apply":
        return "🟢 اپلای کنید", "بر اساس CV شما، اپلای منطقی است."
    if norm == "Conditional":
        return "🟡 مشروط — فقط اگر شرایطش را دارید", "اپلای فقط در صورت رفع/پذیرش محدودیت‌های زیر."
    if norm == "Skip":
        return "🔴 اپلای نکنید (Skip)", "بر اساس CV و ترجیحات شما، رد کردن این آگهی بهتر است."
    if fit is not None:
        if fit >= 75:
            return "🟢 اپلای کنید", "امتیاز تناسب بالا است — اپلای توصیه می‌شود."
        if fit >= 50:
            return "🟡 مشروط", "تناسب متوسط — قبل از اپلای محدودیت‌ها را چک کنید."
        return "🔴 اپلای نکنید", "تناسب پایین — اپلای توصیه نمی‌شود."
    return "⚪ توصیه نامشخص", "نتیجه ارزیابی کامل نبود — evaluation.md را بخوانید."


def _as_str_list(value: Any, *, limit: int = 6) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            out.append(text)
        if len(out) >= limit:
            break
    return out


async def apply_work_result(db: Session, row: WorkJob, result: dict[str, Any]) -> dict:
    """Mark job done and apply side effects. Returns toast/edit hints for logging."""
    job_type = row.job_type
    if job_type == JOB_LINKEDIN_EMAIL:
        out = await _apply_linkedin_email(db, row, result)
    elif job_type in (JOB_LINKEDIN_RESUME, JOB_ATS_REGENERATE):
        out = await _apply_ats(db, row, result)
    elif job_type == JOB_PROJECT_SEND:
        out = await _apply_project_send(db, row, result)
    elif job_type == JOB_VECTOR_SCREEN:
        out = {"ok": True, "message": "vector screen complete"}
    elif job_type == JOB_CODEX_APPLY:
        out = await _apply_codex_apply(db, row, result)
    elif job_type == JOB_SAVE_FILES:
        out = {"ok": bool(result.get("ok")), "message": "files saved to PC folder"}
        if not result.get("ok"):
            out["error"] = result.get("error") or "save_files failed"
    else:
        out = {"ok": False, "error": f"Unknown job type {job_type}"}

    if out.get("ok"):
        row.status = "done"
        row.result_json = json.dumps(result, ensure_ascii=False, default=str)
        row.error_message = None
        row.completed_at = _now()
        db.commit()
    else:
        await fail_work_job(db, row, out.get("error") or "Apply failed")
    return out


async def fail_work_job(db: Session, row: WorkJob, error: str) -> None:
    row.status = "failed"
    row.error_message = (error or "Unknown error")[:2000]
    row.completed_at = _now()
    db.commit()

    # Roll back ATS generating state
    if row.job_type in (JOB_LINKEDIN_RESUME, JOB_ATS_REGENERATE):
        if row.job_type == JOB_ATS_REGENERATE:
            ats = db.get(AtsResume, row.entity_id)
        else:
            ats = db.query(AtsResume).filter(AtsResume.linkedin_job_db_id == row.entity_id).first()
        if ats and ats.status == "generating":
            ats.status = "failed"
            ats.error_message = row.error_message
            db.commit()

    if row.job_type == JOB_CODEX_APPLY and row.payload_json:
        try:
            payload = json.loads(row.payload_json)
            app_id = payload.get("application_id")
            if app_id:
                app = db.get(BotApplication, int(app_id))
                if app:
                    app.status = "failed"
                    app.error_message = row.error_message
                    db.commit()
        except Exception:
            logger.exception("Failed updating BotApplication after Codex failure")

    try:
        from app.telegram.bot import review_bot

        if review_bot.configured:
            chat_id = None
            if row.job_type == JOB_CODEX_APPLY and row.payload_json:
                try:
                    payload = json.loads(row.payload_json)
                    chat_id = payload.get("chat_id") or row.entity_id
                except json.JSONDecodeError:
                    chat_id = row.entity_id
            await review_bot.send_message(
                f"❌ Worker job failed ({row.job_type} #{row.id}): "
                f"{(error or '')[:400]}",
                chat_id=chat_id,
            )
    except Exception:
        logger.exception("Failed to notify Telegram of worker failure")


async def _apply_linkedin_email(db: Session, row: WorkJob, result: dict) -> dict:
    job = db.get(LinkedInJob, row.entity_id)
    if not job:
        return {"ok": False, "error": "LinkedIn job not found"}

    job.email_subject = result.get("email_subject") or ""
    job.email_body = result.get("email_body") or ""
    job.recipient_email = (result.get("recipient_email") or "").strip() or None
    job.status = "draft"
    job.error_message = None
    note = " · Email draft ready"
    if note not in (job.match_reason or ""):
        job.match_reason = (job.match_reason or "") + note
    db.commit()
    db.refresh(job)

    from app.telegram.service import telegram_service

    await telegram_service.notify_linkedin_job_draft(job)
    return {"ok": True, "message": "Email draft applied"}


async def _apply_ats(db: Session, row: WorkJob, result: dict) -> dict:
    if row.job_type == JOB_ATS_REGENERATE:
        ats = db.get(AtsResume, row.entity_id)
        job_db_id = ats.linkedin_job_db_id if ats else None
    else:
        job_db_id = row.entity_id
        ats = db.query(AtsResume).filter(AtsResume.linkedin_job_db_id == job_db_id).first()

    if not ats or not job_db_id:
        return {"ok": False, "error": "ATS resume not found"}

    job = db.get(LinkedInJob, job_db_id)
    out_dir = ATS_DIR / str(job_db_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    first = str(result.get("file_basename") or "Candidate_Resume")
    base_name = _safe_filename(first)

    docx_b64 = result.get("docx_b64")
    if not docx_b64:
        return {"ok": False, "error": "Missing docx_b64 in worker result"}

    docx_path = out_dir / f"{base_name}.docx"
    _write_b64_file(docx_path, docx_b64)

    pdf_path = None
    pdf_b64 = result.get("pdf_b64")
    if pdf_b64:
        pdf_file = out_dir / f"{base_name}.pdf"
        _write_b64_file(pdf_file, pdf_b64)
        pdf_path = str(pdf_file)

    ats.resume_json = result.get("resume_json") or ats.resume_json
    ats.scores_json = result.get("scores_json") or ats.scores_json
    ats.total_score = result.get("total_score")
    ats.keyword_matched = result.get("keyword_matched") or "[]"
    ats.keyword_missing = result.get("keyword_missing") or "[]"
    ats.diff_summary = result.get("diff_summary")
    ats.improvement_tips_json = result.get("improvement_tips_json")
    ats.docx_path = str(docx_path)
    ats.pdf_path = pdf_path
    ats.status = "ready"
    ats.error_message = None
    db.commit()
    db.refresh(ats)

    if result.get("repost", True):
        try:
            from app.telegram.service import telegram_service

            await telegram_service.notify_linkedin_ats_resume(ats.id)
        except Exception:
            logger.exception("ATS notify failed after worker complete for %s", ats.id)

    return {"ok": True, "message": "ATS resume applied", "ats_id": ats.id, "job_title": job.title if job else None}


async def _apply_project_send(db: Session, row: WorkJob, result: dict) -> dict:
    return {"ok": False, "error": "Freelancer bidding has been removed from LinkedIn Job Finder."}


async def _apply_codex_apply(db: Session, row: WorkJob, result: dict) -> dict:
    """Persist Codex package + deliver a structured Telegram update with Improve."""
    import html as html_lib

    from app.ats.docx_export import export_markdown_docx
    from app.telegram.bot import review_bot

    chat_id = result.get("chat_id") or row.entity_id
    telegram_user_id = int(result.get("telegram_user_id") or row.entity_id)
    title = (result.get("title") or "Role").strip()
    company = (result.get("company") or "").strip()
    job_url = (result.get("job_url") or "").strip()
    description = (result.get("description") or "").strip()
    if not description and row.payload_json:
        try:
            description = (json.loads(row.payload_json).get("description") or "").strip()
        except json.JSONDecodeError:
            description = ""

    fit = result.get("fit_score")
    try:
        fit_i = int(fit) if fit is not None and str(fit).strip() != "" else None
    except (TypeError, ValueError):
        fit_i = None
    rec = _normalize_recommendation(result.get("recommendation") or "—")
    summary = (result.get("summary") or "").strip()
    notes = (result.get("ats_notes") or "").strip()
    apply_advice = (result.get("apply_advice") or "").strip()
    pros = _as_str_list(result.get("pros"))
    cons = _as_str_list(result.get("cons"))
    deal_breakers = _as_str_list(result.get("deal_breakers"))
    # Fallback: if agent omitted apply_advice, use summary
    if not apply_advice and summary:
        apply_advice = summary
    out_dir = result.get("output_dir") or ""
    resume_md = (result.get("resume_md") or "").strip()
    evaluation_md = (result.get("evaluation_md") or "").strip()
    improve = bool(result.get("improve"))

    # Hybrid keyword ATS score against the JD (AI phrases + heuristics)
    ats_score = None
    ats_scoring: dict[str, Any] = {}
    resume_struct: dict[str, Any] | None = None
    if resume_md and description:
        try:
            from app.ats.keywords import extract_jd_keywords_hybrid
            from app.ats.score import markdown_resume_to_dict, score_resume

            resume_struct = markdown_resume_to_dict(resume_md)
            try:
                from app.ats.docx_export import _enrich_from_markdown_sections

                resume_struct = _enrich_from_markdown_sections(resume_md, resume_struct)
            except Exception:
                pass
            hybrid = await extract_jd_keywords_hybrid(
                description,
                title=title,
            )
            resume_struct["keywords_from_jd"] = hybrid.get("all") or []
            ats_scoring = score_resume(resume_struct, description, include_pdf=False)
            ats_scoring["hybrid_keywords"] = {
                "must_have": hybrid.get("must_have") or [],
                "claimable": hybrid.get("claimable") or [],
                "missing": hybrid.get("missing") or [],
            }
            ats_score = int(ats_scoring.get("total_score") or 0)
        except Exception:
            logger.exception("ATS score failed for Codex apply %s", row.id)
            try:
                from app.ats.score import score_codex_resume

                ats_scoring = score_codex_resume(resume_md, description)
                ats_score = int(ats_scoring.get("total_score") or 0)
            except Exception:
                logger.exception("Fallback ATS score also failed for Codex apply %s", row.id)

    # Persist / update BotApplication
    app_id = result.get("application_id")
    app: BotApplication | None = None
    if app_id:
        app = db.get(BotApplication, int(app_id))
    if app is None:
        app = BotApplication(telegram_user_id=telegram_user_id)
        db.add(app)

    app.work_job_id = row.id
    app.title = title[:512]
    app.company = company[:256]
    app.job_url = job_url[:1024]
    if description:
        app.description = description[:60000]
    app.fit_score = fit_i
    app.recommendation = rec[:64]
    # Prefer explicit apply advice for dashboard/summary display
    display_summary = apply_advice or summary
    app.summary = display_summary[:5000] if display_summary else None
    app.ats_notes = notes[:5000] if notes else None
    app.ats_score = ats_score
    if ats_scoring:
        app.ats_scores_json = json.dumps(ats_scoring, ensure_ascii=False, default=str)
    if evaluation_md:
        app.evaluation_md = evaluation_md[:200000]
    if resume_md:
        app.resume_md = resume_md[:200000]
    app.output_dir = (out_dir or "")[:1024] or None
    app.status = "ready"
    app.error_message = None
    db.flush()

    # Save DOCX under data/ats/applications/{id}/
    from app.ats.naming import resume_filename, sanitize_job_title

    short_title = sanitize_job_title(
        str(result.get("short_title") or title or "Role"), max_len=60
    )
    # Prefer short title on the BotApplication row for later FA/PDF naming
    if short_title and short_title != "Role":
        app.title = short_title[:512]
        title = short_title

    docx_dir = Path(ATS_DIR) / "applications" / str(app.id)
    docx_dir.mkdir(parents=True, exist_ok=True)
    docx_path = docx_dir / resume_filename(lang="en", job_title=title, ext="docx")
    legacy_docx = docx_dir / "resume.docx"
    eval_path = docx_dir / "evaluation.md"

    b64_docx = result.get("resume_docx_b64")
    if b64_docx:
        try:
            _write_b64_file(docx_path, b64_docx)
            if docx_path.is_file():
                legacy_docx.write_bytes(docx_path.read_bytes())
        except Exception:
            logger.exception("Failed writing resume.docx from worker b64")
            b64_docx = None
    if not docx_path.is_file() and resume_md:
        try:
            export_markdown_docx(resume_md, docx_path)
            if docx_path.is_file():
                legacy_docx.write_bytes(docx_path.read_bytes())
        except Exception:
            logger.exception("Failed generating resume.docx on VPS")
    if evaluation_md:
        eval_path.write_text(evaluation_md, encoding="utf-8")
        app.evaluation_path = str(eval_path)
    if docx_path.is_file():
        app.resume_docx_path = str(docx_path)

    # Persist structured resume + English PDF for inline buttons
    if resume_struct:
        try:
            app.resume_json = json.dumps(resume_struct, ensure_ascii=False, default=str)[:400000]
        except Exception:
            logger.exception("Failed storing resume_json")
        pdf_path = docx_dir / resume_filename(lang="en", job_title=title, ext="pdf")
        try:
            from app.ats.pdf_export import export_resume_pdf

            export_resume_pdf(resume_struct, pdf_path)
            if pdf_path.is_file():
                app.resume_pdf_path = str(pdf_path)
                (docx_dir / "resume.pdf").write_bytes(pdf_path.read_bytes())
        except Exception:
            logger.exception("Failed generating English resume.pdf")

    db.commit()
    db.refresh(app)

    from app.telegram.bot_user_tools import application_actions_markup

    improve_markup = application_actions_markup(app)

    # Structured Telegram message
    esc = html_lib.escape
    role_line = esc(title)
    if company:
        role_line += f" — {esc(company)}"

    header = "🔄 <b>رزومه بهبود یافت</b>" if improve else "✅ <b>رزومه آماده شد</b>"
    verdict_title, verdict_line = _fa_apply_verdict(rec, fit_i)

    def _quote_block(title: str, body_lines: list[str]) -> list[str]:
        body = "\n".join(x for x in body_lines if x is not None and str(x).strip() != "")
        if not body.strip():
            return []
        return ["", f"<b>{title}</b>", f"<blockquote expandable>{body}</blockquote>"]

    advice_bits = [
        f"<b>{esc(verdict_title)}</b>",
        esc(verdict_line),
        f"توصیه انگلیسی: <b>{esc(rec)}</b>"
        + (f" · Fit <b>{fit_i}</b>/100" if fit_i is not None else ""),
    ]
    if apply_advice:
        advice_bits.append(esc(apply_advice[:1500]))

    lines = [header]
    lines.extend(_quote_block("🧭 مشاوره اپلای (بر اساس CV شما)", advice_bits))

    if deal_breakers:
        lines.extend(
            _quote_block(
                "⛔ Deal-breakers",
                [f"• {esc(item[:240])}" for item in deal_breakers],
            )
        )
    if pros:
        lines.extend(
            _quote_block(
                "✅ نقاط قوت / Advantages",
                [f"• {esc(item[:240])}" for item in pros],
            )
        )
    if cons:
        lines.extend(
            _quote_block(
                "⚠️ ریسک‌ها / Risks",
                [f"• {esc(item[:240])}" for item in cons],
            )
        )

    lines.extend(
        [
            "",
            "📌 <b>شغل</b>",
            role_line,
        ]
    )
    if job_url:
        lines.append(f'<a href="{esc(job_url)}">لینک آگهی</a>')

    lines.extend(
        [
            "",
            "📊 <b>امتیازها</b>",
            f"• تناسب (Fit): <b>{fit_i if fit_i is not None else '—'}</b>/100",
            f"• ATS کل: <b>{ats_score if ats_score is not None else '—'}</b>/100"
            + (f" · {esc(str(ats_scoring.get('band') or ''))}" if ats_scoring.get("band") else ""),
        ]
    )
    cats = ats_scoring.get("categories") or {}
    if cats:
        for key, label in (
            ("keyword_match", "Keywords"),
            ("achievements", "Metrics"),
            ("action_verbs", "Verbs"),
            ("skills", "Skills"),
            ("projects", "Projects"),
            ("formatting", "Format"),
            ("readability", "Read"),
            ("grammar", "Grammar"),
        ):
            if key in cats:
                lines.append(f"• {label}: <b>{cats[key]}</b>")
    missing = ats_scoring.get("keyword_missing") or []
    if missing:
        lines.append("• Missing keywords:")
        for kw in missing[:12]:
            lines.append(f"  • {esc(str(kw))}")
    matched = ats_scoring.get("keyword_matched") or []
    if matched:
        lines.append("• Matched keywords:")
        for kw in matched[:12]:
            lines.append(f"  • {esc(str(kw))}")
    if notes:
        lines.extend(_quote_block("💡 نکات رزومه", [esc(notes[:800])]))
    if out_dir:
        lines.extend(["", "📁 <b>ذخیره روی PC</b>", f"<code>{esc(out_dir)}</code>"])
    lines.extend(
        [
            "",
            "📎 فایل‌های <b>evaluation.md</b> و رزومه در ادامه ارسال می‌شوند.",
            "دکمه‌ها: Improve · ترجمه فارسی · PDF",
            "قبل از ارسال واقعی، خودتان مرور کنید.",
        ]
    )

    if review_bot.configured and chat_id:
        await review_bot.send_message(
            "\n".join(lines),
            chat_id=int(chat_id),
            reply_markup=improve_markup,
        )

        # Prefer DOCX resume; still send evaluation.md for the Improve brief
        if eval_path.is_file():
            try:
                await review_bot.send_document(
                    str(eval_path),
                    chat_id=int(chat_id),
                    caption="evaluation.md",
                )
            except Exception:
                logger.exception("Failed sending evaluation.md")
        if docx_path.is_file():
            try:
                await review_bot.send_document(
                    str(docx_path),
                    chat_id=int(chat_id),
                    caption=docx_path.name,
                    reply_markup=improve_markup,
                )
            except Exception:
                logger.exception("Failed sending resume.docx")
        if app.resume_pdf_path and Path(app.resume_pdf_path).is_file():
            try:
                await review_bot.send_document(
                    str(app.resume_pdf_path),
                    chat_id=int(chat_id),
                    caption=Path(app.resume_pdf_path).name,
                )
            except Exception:
                logger.exception("Failed sending resume.pdf")
        elif result.get("resume_md_b64"):
            # Fallback markdown if DOCX failed
            try:
                raw = base64.b64decode(result["resume_md_b64"])
                tmp = docx_dir / "resume.md"
                tmp.write_bytes(raw)
                await review_bot.send_document(
                    str(tmp),
                    chat_id=int(chat_id),
                    caption="resume.md (DOCX failed)",
                    reply_markup=improve_markup,
                )
            except Exception:
                logger.exception("Failed sending resume.md fallback")

    return {
        "ok": True,
        "message": "Codex apply delivered to Telegram",
        "application_id": app.id,
    }
