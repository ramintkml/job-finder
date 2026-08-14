"""Export structured resume JSON to single-column PDF (English + Persian)."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from app.ats.fonts import find_latin_font, find_unicode_font

logger = logging.getLogger(__name__)

FA_HEADINGS = {
    "summary": "خلاصه حرفه‌ای",
    "skills": "مهارت‌های اصلی",
    "projects": "پروژه‌های منتخب",
    "additional": "تجربه تکمیلی",
    "experience": "سوابق شغلی",
    "research": "پژوهش",
    "education": "تحصیلات",
    "languages_certs": "زبان‌ها و گواهینامه‌ها",
}

EN_HEADINGS = {
    "summary": "Professional Summary",
    "skills": "Core Skills",
    "projects": "Selected Projects",
    "additional": "Additional Experience",
    "experience": "Professional Experience",
    "research": "Research",
    "education": "Education",
    "languages_certs": "Languages & Certifications",
}


def _ascii_safe(text: str) -> str:
    return (
        (text or "")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2022", "-")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )


def _has_persian(text: str) -> bool:
    return bool(re.search(r"[\u0600-\u06FF]", text or ""))


def _shape_persian(text: str) -> str:
    """Reshape + bidi for fpdf Arabic/Persian glyphs."""
    if not text or not _has_persian(text):
        return text
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display

        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        logger.exception("Persian reshape failed; writing raw Unicode")
        return text


def _join_bits(*parts: str, sep: str = " | ") -> str:
    return sep.join(p.strip() for p in parts if p and str(p).strip())


class _ResumePDF(FPDF):
    def __init__(self, *, rtl: bool = False, font_path: Path | None = None):
        super().__init__(unit="mm", format="A4")
        self._rtl = rtl
        self._uni = False
        self.set_auto_page_break(auto=True, margin=15)
        if font_path and font_path.is_file():
            try:
                self.add_font("ResumeUni", "", str(font_path))
                # Some TTFs lack a bold face — reuse regular
                self.add_font("ResumeUni", "B", str(font_path))
                self._uni = True
            except Exception:
                logger.exception("Failed loading unicode font %s", font_path)
                self._uni = False

    def write_line(
        self,
        text: str,
        *,
        size: float = 10,
        bold: bool = False,
        h: float = 5,
    ) -> None:
        text = (text or "").rstrip()
        if not text.strip():
            return
        if self._uni:
            rendered = _shape_persian(text) if self._rtl or _has_persian(text) else text
            style = "B" if bold else ""
            self.set_font("ResumeUni", style, size)
        else:
            rendered = (
                _ascii_safe(text)
                .encode("latin-1", "replace")
                .decode("latin-1")
            )
            self.set_font("Helvetica", "B" if bold else "", size)
        self.set_x(self.l_margin)
        align = "R" if self._rtl else "L"
        self.multi_cell(
            self.epw,
            h,
            rendered,
            align=align,
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )


def export_resume_pdf(
    resume: dict[str, Any],
    path: Path,
    *,
    rtl: bool = False,
    headings: dict[str, str] | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    # EN must use a Latin font — B Nazanin breaks Latin glyphs in fpdf.
    font = find_unicode_font(prefer_persian=True) if rtl else find_latin_font()
    pdf = _ResumePDF(rtl=rtl, font_path=font)
    pdf.add_page()
    pdf.set_margins(18, 15, 18)
    pdf.set_x(pdf.l_margin)

    hmap = headings or (FA_HEADINGS if rtl else EN_HEADINGS)

    def write(text: str, *, size: float = 10, bold: bool = False, h: float = 5) -> None:
        pdf.write_line(text, size=size, bold=bold, h=h)

    def heading(key: str) -> None:
        label = hmap.get(key) or key
        write(label, size=11, bold=True, h=6)
        pdf.ln(1)

    def body(text: str) -> None:
        write(str(text or ""), size=10, h=5)
        if text:
            pdf.ln(1)

    def bullets(items: list, *, level: int = 0) -> None:
        for item in items:
            if isinstance(item, dict):
                text = str(item.get("text") or "").strip()
                if text:
                    prefix = "    " * level + ("• " if not rtl else "• ")
                    write(f"{prefix}{text}", size=10, bold=bool(item.get("bold")), h=5)
                bullets(
                    list(item.get("sub_bullets") or item.get("children") or item.get("bullets") or []),
                    level=level + 1,
                )
                continue
            item = str(item or "").strip()
            if not item:
                continue
            prefix = "    " * level + ("• " if not rtl else "• ")
            write(f"{prefix}{item}", size=10, h=5)
        if level == 0:
            pdf.ln(1)

    write(resume.get("full_name") or "Candidate", size=16, bold=True, h=8)
    title = (resume.get("professional_title") or "").strip()
    if title:
        write(title, size=11, bold=True, h=6)

    contact = _join_bits(str(resume.get("email") or ""), str(resume.get("phone") or ""))
    links = _join_bits(
        str(resume.get("linkedin") or ""),
        str(resume.get("github") or ""),
        str(resume.get("portfolio") or ""),
        str(resume.get("location") or ""),
    )
    if contact:
        write(contact, size=9, h=5)
    if links:
        write(links, size=9, h=5)
    pdf.ln(2)

    if resume.get("summary"):
        heading("summary")
        body(str(resume["summary"]))

    skills = resume.get("skills") or {}
    if isinstance(skills, dict) and skills:
        heading("skills")
        for cat, items in skills.items():
            body(f"{cat}: " + ", ".join(str(x) for x in (items or []) if x))
    elif isinstance(skills, list) and skills:
        heading("skills")
        body(", ".join(str(x) for x in skills if x))

    projects = resume.get("projects") or []
    if projects:
        heading("projects")
        for proj in projects:
            name = (proj.get("name") or "").strip()
            sub = (proj.get("subtitle") or "").strip()
            url = (proj.get("url") or proj.get("link") or "").strip()
            meta = _join_bits(sub, url)
            line = f"{name} — {meta}" if meta else name
            bullets([{"text": line, "bold": True, "sub_bullets": list(proj.get("bullets") or [])}])

    additional = resume.get("additional_experience") or []
    if additional:
        heading("additional")
        for block in additional:
            if isinstance(block, str):
                body(block)
                continue
            label = (block.get("title") or block.get("label") or "").strip()
            text = (block.get("text") or block.get("summary") or "").strip()
            if label:
                write(label, size=10, bold=True, h=5)
            if text:
                body(text)
            bullets(list(block.get("bullets") or []))

    experience = resume.get("experience") or []
    if experience:
        heading("experience")
        for role in experience:
            left = " - ".join(
                x
                for x in [
                    (role.get("title") or "").strip(),
                    (role.get("company") or "").strip(),
                ]
                if x
            )
            line = _join_bits(left, (role.get("location") or "").strip(), (role.get("dates") or "").strip())
            write(line, size=10, bold=True, h=5)
            bullets(list(role.get("bullets") or []))

    research = resume.get("research") or []
    if isinstance(research, str) and research.strip():
        heading("research")
        body(research.strip())
    elif isinstance(research, list) and research:
        heading("research")
        for item in research:
            if isinstance(item, str):
                body(item)
            else:
                label = (item.get("title") or "").strip()
                text = (item.get("text") or item.get("summary") or "").strip()
                body(f"{label}: {text}" if label and text else (text or label))

    education = resume.get("education") or []
    if education:
        heading("education")
        for edu in education:
            line = _join_bits(
                (edu.get("degree") or "").strip(),
                (edu.get("school") or "").strip(),
                (edu.get("dates") or "").strip(),
            )
            body(line)

    languages = resume.get("languages") or []
    certs = resume.get("certifications") or []
    if languages or certs:
        heading("languages_certs")
        if isinstance(languages, list):
            for lang in languages:
                body(str(lang))
        elif isinstance(languages, str) and languages.strip():
            body(languages.strip())
        for c in certs:
            body(str(c))

    pdf.output(str(path))
    return path


def export_resume_pdf_fa(resume: dict[str, Any], path: Path) -> Path:
    """Persian PDF via HTML→PDF (WeasyPrint) for correct RTL sentences/bullets."""
    try:
        from app.ats.html_pdf import export_resume_pdf_fa_html

        return export_resume_pdf_fa_html(resume, path)
    except Exception:
        logger.exception("HTML FA PDF failed; falling back to fpdf RTL")
        from app.ats.fonts import find_bnazanin_font

        # Force B Nazanin into fpdf path when possible
        font = find_bnazanin_font()
        if font is not None:
            os.environ.setdefault("ATS_FA_FONT", str(font))
        return export_resume_pdf(resume, path, rtl=True, headings=FA_HEADINGS)
