"""Safe job titles and resume download filenames."""

from __future__ import annotations

import re
from pathlib import Path


def sanitize_job_title(title: str, *, max_len: int = 60) -> str:
    """Short, human job title for folders/filenames (not the whole JD paste)."""
    raw = (title or "").strip()
    if not raw:
        return "Role"
    line = raw.splitlines()[0].strip()
    line = re.sub(r"https?://\S+", "", line).strip()

    lower = line.lower()
    # Marketing / pasted-JD openers → keep a short token, not the essay
    fluff_prefixes = (
        "in the story of ",
        "about the role",
        "job description",
        "we are hiring",
        "we believe",
        "company overview",
    )
    for prefix in fluff_prefixes:
        if lower.startswith(prefix):
            # Try to pull a proper noun after "story of X"
            m = re.match(r"in the story of\s+([A-Za-z0-9]+)", line, re.I)
            if m:
                line = f"{m.group(1)} Role"
            else:
                line = "Target Role"
            break

    line = re.sub(r"[\r\n\t]+", " ", line)
    line = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", line)
    line = re.sub(r"\s+", " ", line).strip(" .-_")
    if len(line) > max_len:
        cut = line[:max_len].rsplit(" ", 1)[0] or line[:max_len]
        line = cut.rstrip(" .-_")
    return line or "Role"


def folder_slug(title: str, company: str = "", *, max_len: int = 48) -> str:
    """Short filesystem folder segment: company_role or role."""
    role = sanitize_job_title(title, max_len=40)
    co = sanitize_job_title(company, max_len=18) if company else ""
    # Drop company if it's already inside the title or looks like JD spam
    if co and co.lower() not in {"company", "unknown", "n/a"}:
        if co.lower() not in role.lower():
            base = f"{co}_{role}"
        else:
            base = role
    else:
        base = role
    slug = re.sub(r"[^A-Za-z0-9]+", "-", base).strip("-").lower()
    slug = re.sub(r"-{2,}", "-", slug)
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug or "role"


def resume_basename(*, lang: str, job_title: str) -> str:
    """Ramin Takmil - CV_en - Job Title  (no extension)."""
    lang = "fa" if str(lang).lower().startswith("fa") else "en"
    title = sanitize_job_title(job_title, max_len=70)
    return f"Ramin Takmil - CV_{lang} - {title}"


def resume_filename(*, lang: str, job_title: str, ext: str) -> str:
    ext = (ext or "docx").lstrip(".").lower()
    if ext == "doc":
        ext = "docx"
    return f"{resume_basename(lang=lang, job_title=job_title)}.{ext}"


def copy_as_named(src: Path, dest_dir: Path, *, lang: str, job_title: str, ext: str) -> Path:
    """Copy src into dest_dir under the canonical resume filename."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / resume_filename(lang=lang, job_title=job_title, ext=ext)
    data = Path(src).read_bytes()
    dest.write_bytes(data)
    return dest
