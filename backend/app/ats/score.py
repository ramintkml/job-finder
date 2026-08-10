"""Score tailored resumes against the ATS guide."""

from __future__ import annotations

import re
from typing import Any

from app.ats.guide import ACTION_VERBS, score_band

METRIC_RE = re.compile(
    r"(\d+\s*%|\d+\+?|\b\d{2,}\b|\bincreased\b|\breduced\b|\bimproved\b|\bsaved\b)",
    re.I,
)


def extract_jd_keywords(job_description: str, ai_keywords: list[str] | None = None) -> list[str]:
    keywords: list[str] = []
    if ai_keywords:
        keywords.extend(str(k).strip() for k in ai_keywords if str(k).strip())
    # Fallback: capitalize tech-looking tokens from JD
    for match in re.finditer(
        r"\b([A-Z][A-Za-z0-9+#.]{1,24}|python|react|fastapi|typescript|llm|rag|docker|aws|azure)\b",
        job_description or "",
        re.I,
    ):
        token = match.group(1).strip()
        if len(token) >= 2:
            keywords.append(token)
    # Dedupe case-insensitive, preserve order
    seen: set[str] = set()
    out: list[str] = []
    for k in keywords:
        key = k.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(k)
    return out[:40]


def _all_bullets(resume: dict[str, Any]) -> list[str]:
    bullets: list[str] = []
    for role in resume.get("experience") or []:
        bullets.extend(str(b).strip() for b in (role.get("bullets") or []) if str(b).strip())
    for proj in resume.get("projects") or []:
        bullets.extend(str(b).strip() for b in (proj.get("bullets") or []) if str(b).strip())
    return bullets


def _resume_text(resume: dict[str, Any]) -> str:
    parts: list[str] = [
        str(resume.get("summary") or ""),
        str(resume.get("professional_title") or ""),
    ]
    skills = resume.get("skills") or {}
    if isinstance(skills, dict):
        for cat, items in skills.items():
            parts.append(str(cat))
            parts.extend(str(x) for x in (items or []))
    elif isinstance(skills, list):
        parts.extend(str(x) for x in skills)
    parts.extend(_all_bullets(resume))
    for role in resume.get("experience") or []:
        parts.append(str(role.get("title") or ""))
        parts.append(str(role.get("company") or ""))
    for proj in resume.get("projects") or []:
        parts.append(str(proj.get("name") or ""))
        parts.append(str(proj.get("subtitle") or ""))
    return "\n".join(parts).lower()


def score_resume_text(cv_text: str, job_description: str) -> dict[str, Any]:
    """Score a user's own resume text (no AI rewrite / no structured resume JSON)."""
    resume = markdown_resume_to_dict(cv_text)
    result = score_resume(resume, job_description, include_pdf=False)
    # User-uploaded DOCX: do not award full "our exporter" formatting marks
    cats = dict(result.get("categories") or {})
    cats["formatting"] = 12
    total = sum(int(v or 0) for v in cats.values())
    result["categories"] = cats
    result["total_score"] = total
    result["band"] = score_band(total)
    return result


def markdown_resume_to_dict(markdown: str) -> dict[str, Any]:
    """Best-effort parse of Codex resume.md into the Ramin CV structured shape."""
    text = (markdown or "").replace("\r\n", "\n").strip()
    lines = text.split("\n")

    name = ""
    title = ""
    summary_parts: list[str] = []
    skills: dict[str, list[str]] = {}
    experience: list[dict[str, Any]] = []
    projects: list[dict[str, Any]] = []
    education: list[dict[str, Any]] = []
    additional: list[dict[str, Any]] = []
    research_parts: list[str] = []
    languages: list[str] = []
    certifications: list[str] = []

    section = "header"
    current: dict[str, Any] | None = None
    current_list: list[dict[str, Any]] | None = None

    def flush_current() -> None:
        nonlocal current, current_list
        if current and current_list is not None:
            if (
                current.get("bullets")
                or current.get("title")
                or current.get("name")
                or current.get("text")
                or current.get("degree")
            ):
                current_list.append(current)
        current = None

    heading_map = {
        "summary": "summary",
        "professional summary": "summary",
        "profile": "summary",
        "skills": "skills",
        "core skills": "skills",
        "technical skills": "skills",
        "experience": "experience",
        "professional experience": "experience",
        "work experience": "experience",
        "projects": "projects",
        "selected projects": "projects",
        "additional experience": "additional",
        "research": "research",
        "education": "education",
        "certifications": "certs",
        "languages & certifications": "certs",
        "languages and certifications": "certs",
    }
    known_headings = set(heading_map.keys())

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("```"):
            continue

        heading = None
        if line.startswith("#"):
            heading = re.sub(r"^#+\s*", "", line).strip()
        elif line.lower() in known_headings:
            heading = line
        elif re.fullmatch(r"[A-Z][A-Z0-9 /&\-]{2,40}", line):
            heading = line

        if heading:
            key = heading_map.get(heading.lower())
            if key:
                flush_current()
                section = key
                if key == "experience":
                    current_list = experience
                elif key == "projects":
                    current_list = projects
                elif key == "education":
                    current_list = education
                elif key == "additional":
                    current_list = additional
                else:
                    current_list = None
                continue
            if section == "header" and not name:
                name = heading
                continue
            if section in ("experience", "projects", "education", "additional"):
                flush_current()
                if section == "experience":
                    bits = [b.strip() for b in re.split(r"\s*\|\s*", heading)]
                    left = bits[0] if bits else heading
                    parts = re.split(r"\s+[-—–]\s+", left, maxsplit=1)
                    dates = ""
                    location = ""
                    if len(bits) > 1 and re.search(r"\d{4}", bits[-1] or ""):
                        dates = bits[-1]
                        if len(bits) > 2:
                            location = bits[1]
                    elif len(bits) == 2:
                        location = bits[1]
                    current = {
                        "title": (parts[0] if parts else left).strip(),
                        "company": (parts[1] if len(parts) > 1 else "").strip(),
                        "location": location,
                        "dates": dates,
                        "bullets": [],
                    }
                    current_list = experience
                elif section == "projects":
                    parts = re.split(r"\s+[—\-–]\s+", heading, maxsplit=1)
                    current = {
                        "name": (parts[0] if parts else heading).strip().strip("*"),
                        "subtitle": (parts[1] if len(parts) > 1 else "").strip(),
                        "bullets": [],
                    }
                    current_list = projects
                elif section == "additional":
                    current = {"title": heading, "text": "", "bullets": []}
                    current_list = additional
                else:
                    current = {"degree": heading, "school": "", "dates": "", "bullets": []}
                    current_list = education
                continue

        bullet = False
        body = line
        if re.match(r"^([\-\*\u2022•]|\d+[.)])\s+", line):
            bullet = True
            body = re.sub(r"^([\-\*\u2022•]|\d+[.)])\s+", "", line).strip()

        if section == "header":
            if not name:
                name = body
            elif not title and len(body) < 120 and "@" not in body:
                title = body
            continue
        if section == "summary":
            summary_parts.append(body)
            continue
        if section == "skills":
            if ":" in body:
                cat, rest = body.split(":", 1)
                items = [x.strip() for x in re.split(r"[,|/]", rest) if x.strip()]
                if cat.strip():
                    skills[cat.strip()] = items
            else:
                items = [x.strip() for x in re.split(r"[,|/]", body) if x.strip()]
                if items:
                    skills.setdefault("Skills", []).extend(items)
            continue
        if section == "research":
            research_parts.append(body)
            continue
        if section == "certs":
            if body.lower().startswith("english") or "ielts" in body.lower():
                languages.append(body)
            else:
                certifications.append(body)
            continue
        if section in ("experience", "projects", "education", "additional"):
            if current is None:
                if section == "experience":
                    current = {"title": body, "company": "", "dates": "", "bullets": []}
                    current_list = experience
                elif section == "projects":
                    current = {"name": body, "subtitle": "", "bullets": []}
                    current_list = projects
                elif section == "additional":
                    current = {"title": body, "text": "", "bullets": []}
                    current_list = additional
                else:
                    current = {"degree": body, "school": "", "dates": "", "bullets": []}
                    current_list = education
                if not bullet:
                    continue
            if bullet:
                current.setdefault("bullets", []).append(body)
            elif section == "additional" and not current.get("text"):
                current["text"] = body
            continue

    flush_current()

    if not experience and not projects:
        bullets = []
        for ln in lines:
            cleaned = re.sub(r"^[\u2022\-\*\u2013\u2014•]\s*", "", ln.strip()).strip()
            if len(cleaned) >= 20:
                bullets.append(cleaned)
        if bullets:
            experience = [{"title": "", "company": "", "bullets": bullets[:100]}]

    return {
        "full_name": name,
        "professional_title": title,
        "summary": " ".join(summary_parts).strip() or text[:800],
        "skills": skills,
        "experience": experience,
        "projects": projects,
        "additional_experience": additional,
        "research": " ".join(research_parts).strip(),
        "education": education,
        "languages": languages,
        "certifications": certifications,
    }


def score_codex_resume(resume_md: str, job_description: str) -> dict[str, Any]:
    """Score a Codex-generated resume with the same ATS method as Freelancer automation.

    Uses structured parsing + score_resume. Full formatting marks apply because we
    export through our single-column DOCX exporter.
    """
    resume = markdown_resume_to_dict(resume_md)
    return score_resume(resume, job_description, include_pdf=False)


def score_resume(
    resume: dict[str, Any],
    job_description: str,
    *,
    include_pdf: bool = False,
) -> dict[str, Any]:
    bullets = _all_bullets(resume)
    text = _resume_text(resume)
    # Pipeline v2: keywords_from_jd is Claim+Bridge only — do NOT re-merge Omit JD tokens
    ai_kw = resume.get("keywords_from_jd")
    if isinstance(ai_kw, list) and ai_kw:
        keywords: list[str] = []
        seen: set[str] = set()
        for k in ai_kw:
            s = str(k).strip()
            if not s:
                continue
            key = s.lower()
            if key in seen:
                continue
            seen.add(key)
            keywords.append(s)
        keywords = keywords[:40]
    else:
        keywords = extract_jd_keywords(job_description, None)

    matched: list[str] = []
    missing: list[str] = []
    for kw in keywords:
        if kw.lower() in text:
            matched.append(kw)
        else:
            missing.append(kw)
    kw_ratio = (len(matched) / len(keywords)) if keywords else 0.5
    keyword_score = round(20 * kw_ratio)

    if bullets:
        with_metric = sum(1 for b in bullets if METRIC_RE.search(b))
        achievements = round(15 * (with_metric / len(bullets)))
        verb_hits = sum(
            1 for b in bullets if any(b.lower().startswith(v) for v in ACTION_VERBS)
        )
        action_verbs = round(10 * (verb_hits / len(bullets)))
    else:
        achievements = 0
        action_verbs = 0

    readability = 10
    if any(len(b.split()) > 25 for b in bullets):
        readability -= 2
    if any(b.count(" and ") >= 2 and "," in b for b in bullets):
        readability -= 2
    if bullets:
        starts_verb = [any(b.lower().startswith(v) for v in ACTION_VERBS) for b in bullets]
        if any(starts_verb) and not all(starts_verb):
            readability -= 2
    if isinstance(resume.get("experience"), list):
        for role in resume["experience"]:
            if isinstance(role.get("description"), str) and role["description"].strip():
                readability -= 2
                break
    readability = max(0, readability)

    skills = resume.get("skills") or {}
    if isinstance(skills, dict) and len(skills) >= 1:
        skills_score = 10
    elif isinstance(skills, list) and skills:
        skills_score = 6
    else:
        skills_score = 0

    projects = resume.get("projects") or []
    projects_score = 10 if projects else 0

    # DOCX/single-column export is enforced by our generator → full formatting marks
    formatting = 20
    if include_pdf:
        formatting = 18  # slight caution: PDF only when requested

    grammar = 5
    # Light heuristic: mixed bullet end punctuation
    if bullets:
        ends_period = [b.rstrip().endswith(".") for b in bullets]
        if any(ends_period) and not all(ends_period):
            grammar -= 1
    grammar = max(0, grammar)

    categories = {
        "formatting": formatting,
        "keyword_match": keyword_score,
        "achievements": achievements,
        "action_verbs": action_verbs,
        "readability": readability,
        "skills": skills_score,
        "projects": projects_score,
        "grammar": grammar,
    }
    total = sum(categories.values())
    return {
        "total_score": total,
        "band": score_band(total),
        "categories": categories,
        "keyword_matched": matched,
        "keyword_missing": missing,
        "max_scores": {
            "formatting": 20,
            "keyword_match": 20,
            "achievements": 15,
            "action_verbs": 10,
            "readability": 10,
            "skills": 10,
            "projects": 10,
            "grammar": 5,
        },
    }
