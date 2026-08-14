"""Parse documents/base_cv.txt (or equivalent) and export DOCX + PDF."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.ats.naming import resume_filename
from app.ats.selected_projects import ensure_selected_projects

_HEADINGS = {
    "professional summary": "summary",
    "core skills": "skills",
    "selected projects": "projects",
    "additional experience": "additional",
    "professional experience": "experience",
    "research": "research",
    "education": "education",
    "languages & certifications": "certs",
    "languages and certifications": "certs",
}

_ROLE_START = re.compile(
    r"^(Full-Stack|AI Specialist|Project Team|Teaching Assistant|Software|Engineer|Developer)\b",
    re.I,
)


def parse_base_cv_text(text: str) -> dict[str, Any]:
    lines = (text or "").replace("\r\n", "\n").split("\n")
    name = ""
    title = ""
    email = ""
    phone = ""
    linkedin = ""
    github = ""
    location = ""
    summary: list[str] = []
    skills: dict[str, list[str]] = {}
    projects: list[dict[str, Any]] = []
    additional: list[dict[str, Any]] = []
    experience: list[dict[str, Any]] = []
    research: list[str] = []
    education: list[dict[str, Any]] = []
    languages: list[str] = []
    certs: list[str] = []

    section = "header"
    current_proj: dict[str, Any] | None = None
    current_role: dict[str, Any] | None = None

    def is_heading(line: str) -> str | None:
        if re.fullmatch(r"[A-Z][A-Z0-9 /&]{3,40}", line):
            return _HEADINGS.get(line.lower())
        return _HEADINGS.get(line.lower())

    i = 0
    while i < len(lines):
        raw = lines[i]
        i += 1
        stripped = raw.strip()
        if not stripped:
            continue
        key = is_heading(stripped)
        if key:
            current_proj = None
            current_role = None
            section = key
            continue

        if section == "header":
            if not name:
                name = stripped
            elif not title and "@" not in stripped and len(stripped) < 80:
                title = stripped
            elif "|" in stripped:
                for part in [p.strip() for p in stripped.split("|")]:
                    if "@" in part:
                        email = part
                    elif re.search(r"\+?\d[\d\s\-()]{6,}", part):
                        phone = part
                    elif "linkedin" in part.lower():
                        linkedin = part
                    elif "github" in part.lower():
                        github = part
                    else:
                        location = part
            continue

        if section == "summary":
            summary.append(stripped)
            continue

        if section == "skills":
            if ":" in stripped:
                cat, rest = stripped.split(":", 1)
                items = [x.strip() for x in rest.split(",") if x.strip()]
                if cat.strip():
                    skills[cat.strip()] = items
            continue

        if section == "projects":
            indent = len(raw) - len(raw.lstrip(" "))
            is_bullet = bool(re.match(r"^[-*•]\s+", stripped))
            body = re.sub(r"^[-*•]\s+", "", stripped).strip()
            if is_bullet and indent < 2:
                current_proj = {"name": body, "subtitle": "", "url": "", "bullets": []}
                # Pull URL-looking tail after em dash
                if "github.com" in body.lower() or "http" in body.lower() or ".top" in body.lower():
                    parts = re.split(r"\s+[—–]\s+", body, maxsplit=1)
                    if len(parts) == 2 and (
                        "github" in parts[1].lower()
                        or "http" in parts[1].lower()
                        or ".top" in parts[1].lower()
                        or ".ir" in parts[1].lower()
                    ):
                        current_proj["name"] = parts[0].strip()
                        current_proj["url"] = parts[1].strip()
                projects.append(current_proj)
            elif current_proj is not None and (is_bullet or indent >= 2):
                current_proj.setdefault("bullets", []).append(body)
            elif current_proj is None:
                current_proj = {"name": body, "subtitle": "", "url": "", "bullets": []}
                projects.append(current_proj)
            continue

        if section == "additional":
            if "—" in stripped or "–" in stripped:
                left, right = re.split(r"\s+[—–]\s+", stripped, maxsplit=1)
                additional.append({"title": left.strip(), "text": right.strip(), "bullets": []})
            else:
                additional.append({"title": stripped, "text": "", "bullets": []})
            continue

        if section == "experience":
            looks_role = ("|" in stripped and re.search(r"\d{4}", stripped)) or bool(
                _ROLE_START.match(stripped)
            )
            if looks_role and "—" in stripped or looks_role and "–" in stripped:
                bits = [b.strip() for b in stripped.split("|")]
                left = bits[0]
                parts = re.split(r"\s+[—–]\s+", left, maxsplit=1)
                dates = bits[-1] if len(bits) > 1 and re.search(r"\d{4}|Present|month", bits[-1], re.I) else ""
                location = ""
                if len(bits) == 3:
                    location = bits[1]
                    dates = bits[2]
                elif len(bits) == 2 and not dates:
                    location = bits[1]
                current_role = {
                    "title": (parts[0] if parts else left).strip(),
                    "company": (parts[1] if len(parts) > 1 else "").strip(),
                    "location": location,
                    "dates": dates,
                    "bullets": [],
                }
                experience.append(current_role)
            elif current_role is not None:
                current_role.setdefault("bullets", []).append(stripped)
            else:
                current_role = {
                    "title": stripped,
                    "company": "",
                    "location": "",
                    "dates": "",
                    "bullets": [],
                }
                experience.append(current_role)
            continue

        if section == "research":
            research.append(stripped)
            continue

        if section == "education":
            education.append({"degree": stripped, "school": "", "dates": "", "gpa": ""})
            continue

        if section == "certs":
            if stripped.lower().startswith("english") or "ielts" in stripped.lower():
                languages.append(stripped)
            elif stripped.lower().startswith("references"):
                certs.append(stripped)
            else:
                certs.append(stripped)

    resume = {
        "full_name": name or "Ramin Takmil",
        "professional_title": title or "AI Specialist / Full-Stack Developer",
        "email": email,
        "phone": phone,
        "linkedin": linkedin,
        "github": github,
        "location": location,
        "summary": " ".join(summary).strip(),
        "skills": skills,
        "projects": projects,
        "additional_experience": additional,
        "experience": experience,
        "research": " ".join(research).strip(),
        "education": education,
        "languages": languages,
        "certifications": certs,
    }
    return ensure_selected_projects(resume, job_text="")


def export_base_cv_files(text: str, dest_dir: Path) -> tuple[Path, Path]:
    """Write English base CV DOCX + PDF. Returns (docx_path, pdf_path)."""
    from app.ats.docx_export import export_resume_docx
    from app.ats.pdf_export import export_resume_pdf

    dest_dir.mkdir(parents=True, exist_ok=True)
    resume = parse_base_cv_text(text)
    docx_path = dest_dir / resume_filename(lang="en", job_title="Base", ext="docx")
    pdf_path = dest_dir / resume_filename(lang="en", job_title="Base", ext="pdf")
    export_resume_docx(resume, docx_path)
    export_resume_pdf(resume, pdf_path)
    return docx_path, pdf_path
