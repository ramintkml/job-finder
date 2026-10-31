"""Format projects from the current user's resume without injecting fixed facts."""
from __future__ import annotations

import re
from typing import Any


def apply_projects_to_markdown(markdown: str, resume: dict[str, Any]) -> str:
    """Replace the Selected Projects section with parent + 4–6 sub-bullets."""
    projects = resume.get("projects") or []
    lines = ["## Selected Projects"]
    for proj in projects:
        name = str(proj.get("name") or "").strip()
        url = str(proj.get("url") or proj.get("link") or "").strip()
        title = f"{name} — {url}" if url else name
        lines.append(title)
        bullets = list(proj.get("bullets") or [])[:6]
        for b in bullets:
            s = str(b).strip()
            if s:
                lines.append(f"- {s}")
        lines.append("")
    block = "\n".join(lines).rstrip() + "\n\n"
    text = (markdown or "").replace("\r\n", "\n")
    m = re.search(r"^##\s+Selected Projects\s*$", text, re.I | re.M)
    if not m:
        return text.rstrip() + "\n\n" + block
    rest = text[m.end() :]
    m2 = re.search(r"^##\s+", rest, re.M)
    after = rest[m2.start() :] if m2 else ""
    return text[: m.start()] + block + after.lstrip("\n")


def ensure_selected_projects(
    resume: dict[str, Any],
    *,
    job_text: str = "",
) -> dict[str, Any]:
    """Keep only projects supplied by the resume pipeline; never inject operator facts."""
    return resume


def project_markdown_rules() -> str:
    return "SELECTED PROJECTS: include only projects supported by this user's base CV. Preserve supplied links; never invent projects, claims, dates, or metrics."
