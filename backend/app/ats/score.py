"""Score tailored resumes against the ATS guide."""

from __future__ import annotations

import re
from typing import Any

from app.ats.guide import ACTION_VERBS, score_band

METRIC_RE = re.compile(
    r"(\d+\s*%|\d+\+?|\b\d{2,}\b|\bincreased\b|\breduced\b|\bimproved\b|\bsaved\b)",
    re.I,
)

# JD boilerplate / country words that must never be treated as ATS skills
_KEYWORD_JUNK = {
    "location",
    "united",
    "states",
    "about",
    "client",
    "opportunity",
    "responsibilities",
    "requirements",
    "benefits",
    "perks",
    "note",
    "show",
    "more",
    "less",
    "equal",
    "range",
    "package",
    "compensation",
    "salary",
    "remotehunter",
    "employer",
    "record",
    "purpose",
    "description",
    "title",
    "company",
    "unknown",
    "url",
    "https",
    "http",
    "www",
    "source",
    "bridge",
    "untrusted",
    "posting",
    "the",
    "and",
    "for",
    "with",
    "from",
    "this",
    "that",
    "our",
    "their",
    "your",
    "you",
    "they",
    "will",
    "must",
    "have",
    "has",
    "are",
    "was",
    "were",
    "been",
    "being",
    "into",
    "onto",
    "over",
    "under",
    "role",
    "team",
    "jobs",
    "view",
}


def _looks_like_link_tail(text: str) -> bool:
    t = (text or "").lower()
    return any(
        x in t
        for x in (
            "github.com",
            "http",
            ".top",
            ".ir",
            ".com",
            ".io",
            "staging",
            "live",
            "stg.bendly",
        )
    )


def _strip_inline_md(text: str) -> str:
    """Remove bold/italic/code markers Codex sometimes wraps around titles."""
    s = (text or "").strip()
    s = re.sub(r"\*+|_+|`+", "", s)
    return s.strip()


def _looks_like_project_title(line: str) -> bool:
    """Plain 'Name — github/url' lines start a new project (not a bullet)."""
    s = _strip_inline_md(line)
    if not s or s.startswith(("-", "*", "•")):
        return False
    if not re.search(r"\s+[—\-–]\s+", s):
        return False
    return _looks_like_link_tail(s) or len(s) <= 140


def _looks_like_role_title(line: str) -> bool:
    """Plain 'Title — Company | Location | dates' starts a new experience role."""
    s = _strip_inline_md(line)
    if not s or s.startswith(("-", "*", "•")):
        return False
    if "|" in s and re.search(r"\d{4}|Present|months?", s, re.I):
        return True
    if re.match(r"^[A-Z][A-Za-z0-9 /&+().-]{2,60}\s+[—–-]\s+\S+", s) and len(s) <= 140:
        if re.search(
            r"Developer|Engineer|Specialist|Manager|Assistant|Lead|Intern|Consultant|Teacher|Teaching",
            s,
            re.I,
        ):
            return True
    return False


def _parse_role_line(line: str) -> dict[str, Any]:
    clean = _strip_inline_md(line)
    bits = [b.strip() for b in re.split(r"\s*\|\s*", clean)]
    left = bits[0] if bits else clean
    parts = re.split(r"\s+[—–-]\s+", left, maxsplit=1)
    dates = ""
    location = ""
    if len(bits) > 1 and re.search(r"\d{4}|Present|months?", bits[-1] or "", re.I):
        dates = bits[-1]
        if len(bits) > 2:
            location = bits[1]
    elif len(bits) == 2:
        location = bits[1]
    return {
        "title": (parts[0] if parts else left).strip(),
        "company": (parts[1] if len(parts) > 1 else "").strip(),
        "location": location,
        "dates": dates,
        "bullets": [],
    }


def _looks_like_edu_line(line: str) -> bool:
    s = (line or "").strip()
    if not s or s.startswith(("-", "*", "•")):
        return False
    return bool(re.search(r"\b(MSc|BSc|PhD|Bachelor|Master|University|GPA)\b", s, re.I))


def _is_junk_keyword(keyword: str) -> bool:
    kl = re.sub(r"[^a-z0-9\u0600-\u06ff+#.\s'-]+", " ", (keyword or "").lower()).strip()
    if not kl or kl in _KEYWORD_JUNK:
        return True
    parts = [p for p in re.split(r"\s+", kl) if p]
    if parts and (parts[0] in _KEYWORD_JUNK or all(p in _KEYWORD_JUNK for p in parts)):
        return True
    return False


def normalize_text(value: str) -> str:
    import unicodedata
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value or "").lower().translate(str.maketrans("يك٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "یک01234567890123456789")).replace("\u200c", " ")).strip()


def keyword_in_text(keyword: str, text: str) -> bool:
    raw, hay = normalize_text(keyword), normalize_text(text)
    if not raw or not hay: return False
    aliases = {"postgres": "postgresql", "js": "javascript", "ts": "typescript", "k8s": "kubernetes"}
    forms = {raw, aliases.get(raw, raw)}
    forms.update(k for k,v in aliases.items() if v == raw)
    for form in forms:
        pattern = re.escape(form).replace(r"\ ", r"[\s\u200c-]+")
        if re.search(r"(?<![\w+#])" + pattern + r"(?![\w+#])", hay): return True
    return False


def extract_jd_keywords(job_description: str, ai_keywords: list[str] | None = None) -> list[str]:
    keywords: list[str] = []
    ai_set: set[str] = set()
    if ai_keywords:
        for k in ai_keywords:
            s = str(k).strip()
            if s:
                keywords.append(s)
                ai_set.add(s.lower())
    for match in re.finditer(
        r"\b([A-Z][A-Za-z0-9+#.]{1,24}|[Pp]ython|[Rr]eact|[Ff]astAPI|[Tt]ype[Ss]cript|LLMs?|RAG|[Dd]ocker|AWS|[Aa]zure)\b",
        job_description or "",
    ):
        token = match.group(1).strip()
        if len(token) >= 2:
            keywords.append(token)
    seen: set[str] = set()
    out: list[str] = []
    for k in keywords:
        if _is_junk_keyword(k):
            continue
        if len(k) < 3 and k.upper() not in {"AI", "ML", "CI", "CD", "AWS", "SQL", "RAG", "API"}:
            continue
        if "linkedin.com" in k.lower() or k.lower().startswith("http"):
            continue
        if "." in k and not re.search(r"(js|sql|net|py)$", k.lower()):
            continue
        if k.lower() not in ai_set and not _looks_like_skill_token(k):
            continue
        key = k.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(k)
    # Preserve Persian phrases and classify frequent JD words separately from skills.
    if re.search(r"[آ-ی]", job_description or ""):
        for term in ("مدیریت پروژه", "تحلیل داده", "یادگیری ماشین", "پایگاه داده", "توسعه نرم افزار", "طراحی رابط کاربری", "کار تیمی", "زبان انگلیسی", "ارتباط با مشتری"):
            if keyword_in_text(term, job_description) and term not in out: out.append(term)
    return out[:40]


def _looks_like_skill_token(token: str) -> bool:
    t = (token or "").strip()
    if re.search(r"[0-9+#./]", t):
        return True
    if re.search(r"[a-z][A-Z]", t):
        return True
    if t.isupper() and 2 <= len(t) <= 5:
        return True
    return t.lower() in {
        "python",
        "react",
        "fastapi",
        "flask",
        "typescript",
        "javascript",
        "docker",
        "postgres",
        "postgresql",
        "llm",
        "llms",
        "rag",
        "aws",
        "azure",
        "gcp",
        "pytorch",
        "tensorflow",
        "chromadb",
        "saas",
        "fintech",
        "prompt",
        "anthropic",
        "claude",
        "codex",
        "cursor",
        "postgresql",
        "postgres",
    }


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
    cats["formatting"] = 0
    total = sum(int(v or 0) for v in cats.values())
    result["categories"] = cats
    result["total_score"] = result.get("coverage_score")
    result["band"] = score_band(result["total_score"]) if result["total_score"] is not None else "Unassessed"
    return result


def markdown_resume_to_dict(markdown: str) -> dict[str, Any]:
    """Best-effort parse of Codex resume.md into the Ramin CV structured shape."""
    text = (markdown or "").replace("\r\n", "\n").strip()
    lines = text.split("\n")

    name = ""
    title = ""
    email = ""
    phone = ""
    linkedin = ""
    github = ""
    location = ""
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
        "خلاصه": "summary", "خلاصه حرفه‌ای": "summary", "خلاصه حرفه ای": "summary",
        "مهارت‌ها": "skills", "مهارت ها": "skills", "مهارت‌های کلیدی": "skills",
        "پروژه‌ها": "projects", "پروژه های منتخب": "projects", "پروژه‌های منتخب": "projects",
        "سوابق شغلی": "experience", "تجربه کاری": "experience", "تحصیلات": "education",
        "زبان‌ها و گواهینامه‌ها": "certs", "پژوهش": "research",
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
            clean = _strip_inline_md(body)
            low = clean.lower()
            if "@" in clean or "linkedin" in low or "github" in low or re.search(
                r"\+?\d[\d\s\-()]{6,}", clean
            ):
                for part in [p.strip() for p in clean.split("|")]:
                    pl = part.lower()
                    if "@" in part and not email:
                        email = part
                    elif re.search(r"\+?\d[\d\s\-()]{6,}", part) and not phone:
                        phone = part
                    elif "linkedin" in pl and not linkedin:
                        linkedin = re.sub(r"^https?://(www\.)?", "", part, flags=re.I).rstrip("/")
                    elif "github" in pl and not github:
                        github = re.sub(r"^https?://(www\.)?", "", part, flags=re.I).rstrip("/")
                    elif re.search(r"(remote|iran|australia|germany|usa|uk)", part, re.I) and not location:
                        location = part
                continue
            if not name:
                name = clean
            elif not title and len(clean) < 120:
                title = clean
            continue
        if section == "summary":
            summary_parts.append(_strip_inline_md(body) if "**" in body or "__" in body else body)
            continue
        if section == "skills":
            clean = _strip_inline_md(body)
            if ":" in clean:
                cat, rest = clean.split(":", 1)
                items = [x.strip() for x in re.split(r"[,;/|]", rest) if x.strip()]
                if cat.strip():
                    skills[cat.strip()] = items
            else:
                items = [x.strip() for x in re.split(r"[,;/|]", clean) if x.strip()]
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
            if (
                section == "experience"
                and not bullet
                and _looks_like_role_title(body)
            ):
                flush_current()
                current = _parse_role_line(body)
                current_list = experience
                continue
            if (
                section == "education"
                and not bullet
                and _looks_like_edu_line(body)
            ):
                flush_current()
                current = {"degree": body, "school": "", "dates": "", "bullets": []}
                current_list = education
                continue
            if (
                section == "projects"
                and not bullet
                and _looks_like_project_title(body)
            ):
                flush_current()
                parts = re.split(r"\s+[—\-–]\s+", body, maxsplit=1)
                url = ""
                name_p = body
                if len(parts) == 2 and _looks_like_link_tail(parts[1]):
                    name_p = parts[0].strip()
                    url = parts[1].strip()
                current = {
                    "name": name_p.strip().strip("*"),
                    "subtitle": "",
                    "url": url,
                    "bullets": [],
                }
                current_list = projects
                continue
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
        "email": email,
        "phone": phone,
        "linkedin": linkedin,
        "github": github,
        "location": location,
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

    Uses structured parsing and the versioned internal coverage assessment.
    Actual file health must be inspected separately after export.
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
    keywords = resume.get("keywords_from_jd")
    if not isinstance(keywords, list) or not keywords:
        keywords = extract_jd_keywords(job_description, None)
    keywords = list(dict.fromkeys(str(k).strip() for k in keywords if str(k).strip()))[:60]
    required = resume.get("required_keywords") or []
    matched = [k for k in keywords if keyword_in_text(k, text)]
    missing = [k for k in keywords if k not in matched]
    weight = lambda k: 3 if any(normalize_text(k)==normalize_text(x) for x in required) else 1
    denominator = sum(weight(k) for k in keywords)
    coverage = round(100 * sum(weight(k) for k in matched) / denominator) if denominator else None
    if not text.strip(): coverage = 0 if denominator else None
    has_content = bool(bullets or resume.get("skills") or resume.get("summary"))
    metric_re = re.compile(r"(?:[0-9۰-۹٠-٩]+\s*(?:%|٪|percent|درصد|users|کاربر|hours|ساعت|requests|درخواست)|(?:reduced|increased|کاهش|افزایش)[^.!؟]{0,50}[0-9۰-۹٠-٩]+)", re.I)
    metric_count = sum(bool(metric_re.search(str(b))) for b in bullets)
    verbs = (*ACTION_VERBS, "ساختم", "طراحی", "پیاده", "توسعه", "بهبود", "خودکار", "کاهش", "افزایش", "مدیریت")
    verb_count = sum(any(normalize_text(str(b)).startswith(v) for v in verbs) for b in bullets)
    readability = max(0, 10 - sum(len(str(b).split())>35 for b in bullets)) if bullets else 0
    categories = {
        "formatting": 0, # Only the actual exported artifact can establish file health.
        "keyword_match": round((coverage or 0) * .6),
        "achievements": round(10 * metric_count / len(bullets)) if bullets else 0,
        "action_verbs": round(10 * verb_count / len(bullets)) if bullets else 0,
        "readability": readability,
        "skills": 10 if resume.get("skills") else 0,
        "projects": 0, # Project presence alone is not quality or job fit.
        "grammar": 0, # Punctuation is not a grammar assessment.
    }
    evidence = []
    for term in keywords:
        snippets = [str(b) for b in bullets if keyword_in_text(term,str(b))]
        evidence.append({"requirement":term,"required":weight(term)==3,"status":"covered" if term in matched else "not_in_resume","resume_evidence":snippets[:2],"action":"بررسی شود؛ فقط با سابقه تأییدشده اضافه شود." if term in missing else "پوشش داده شده است."})
    return {"method_version":"3.0", "assessment_type":"internal_review", "total_score":coverage,
            "band":score_band(coverage) if coverage is not None else "Unassessed",
            "categories":categories,"max_scores":{"keyword_match":60,"achievements":10,"action_verbs":10,"readability":10,"skills":10,"projects":0,"grammar":0,"formatting":0},
            "keyword_matched":matched,"keyword_missing":missing,"requirements":evidence,
            "coverage_score":coverage,"content_score":sum(categories.values()) if has_content else 0,
            "file_health":{"status":"not_checked"},
            "notice":"ارزیابی داخلی برنامه؛ امتیاز سامانه کارفرما یا احتمال قبولی نیست."}
