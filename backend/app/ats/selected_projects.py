"""Canonical Selected Projects for every tailored resume.

Always include all five. Reorder by JD overlap. Keep links. Tailor bullets only
from verified facts — never drop a project.
"""

from __future__ import annotations

import re
from typing import Any

CANONICAL_PROJECTS: list[dict[str, Any]] = [
    {
        "key": "bendly",
        "name": "Bendly — Construction Manufacturing Platform",
        "url": "github.com/Bendly-app | https://stg.bendly.io/",
        "match": ("bendly", "construction manufacturing", "flashing"),
        "tokens": (
            "next.js",
            "react",
            "typescript",
            "nestjs",
            "graphql",
            "docker",
            "saas",
            "b2b",
            "pwa",
            "cursor",
            "claude code",
            "codex",
            "agentic",
        ),
        "bullets": [
            "Full-stack SaaS for custom flashing design, ordering, and manufacturing tracking in the construction industry.",
            "Built customer-facing Next.js 16 / React 19 / TypeScript dashboard with SVG canvas design editor, order management, and PDF export.",
            "Integrated NestJS GraphQL backend; Zustand, Tailwind CSS, shadcn/ui, PWA; Dockerized services.",
            "Collaborated remotely with an Australian product team via Git/GitHub; CI/CD-style Docker staging deploys at https://stg.bendly.io/.",
            "Developed with Cursor, Claude Code, and Codex using agentic coding, agent skills, and prompt engineering/enhancing; LLM-assisted testing; subagents for security and performance review.",
        ],
    },
    {
        "key": "medinex",
        "name": "Medinex — Clinic Outreach Email Platform",
        "url": "github.com/ramintkml/medinex | medinex.top",
        "match": ("medinex", "clinic outreach"),
        "tokens": (
            "flask",
            "react",
            "typescript",
            "sqlite",
            "docker",
            "email",
            "saas",
            "rtl",
            "cursor",
            "claude code",
            "codex",
            "agentic",
        ),
        "bullets": [
            "Farsi multi-user SaaS for personalized CV/outreach email campaigns to Australian medical clinics (medinex.top).",
            "Built Flask REST APIs + React 19 / TypeScript RTL PWA with SQLite, scheduling workers, and IMAP reply polling.",
            "Implemented clinic catalog crawler, Excel/PDF uploads, templates, send-window controls, and PDF campaign reports.",
            "Added monetization (trial, card-to-card, TON invoices) and Telegram-backed support; Docker + GitHub delivery loops.",
            "Developed with Cursor, Claude Code, and Codex using agentic coding, agent skills, and prompt engineering/enhancing; LLM-assisted testing; subagents for security and performance review.",
        ],
    },
    {
        "key": "ot-clinic",
        "name": "OT Clinic (Fereshtegan Rehab)",
        "url": "github.com/ramintkml/ot-clinic | fereshteganrehab.ir (live)",
        "match": ("ot clinic", "fereshtegan", "occupational therapy"),
        "tokens": (
            "next.js",
            "flask",
            "sqlalchemy",
            "docker",
            "production",
            "rtl",
            "scheduling",
            "saas",
        ),
        "bullets": [
            "End-to-end Persian occupational therapy clinic system: public site plus staff dashboard for scheduling, finance, and patients.",
            "Shipped Next.js 15 (RTL, Jalali) + Flask 3 REST API with SQLAlchemy and role-based auth (admin / secretary).",
            "Implemented daily scheduling with OR-Tools, PDF export, and Excel finance/salary reporting.",
            "Deployed live at fereshteganrehab.ir for a multi-therapist clinic; Docker + GitHub CI/CD release loops.",
        ],
    },
    {
        "key": "job-finder",
        "name": "Job Finder — Freelancer & LinkedIn Automation",
        "url": "github.com/ramintkml/job-finder",
        "match": ("job finder", "freelancer", "linkedin automation"),
        "tokens": (
            "fastapi",
            "chromadb",
            "rag",
            "vector",
            "llm",
            "groq",
            "telegram",
            "python",
            "prompt",
            "cursor",
            "claude code",
            "codex",
            "agentic",
        ),
        "bullets": [
            "Full-stack automation app (github.com/ramintkml/job-finder): monitors Freelancer.com and LinkedIn jobs and matches them via ChromaDB vector search.",
            "Developed FastAPI-based systems and Python services for AI screening and proposal generation via Groq/LLM APIs.",
            "Designed and refined prompts in a Telegram human-in-the-loop approve/skip workflow (React PWA).",
            "Built with Git/GitHub; Cursor, Claude Code, and Codex; agentic coding, agent skills, and prompt engineering/enhancing; LLM-assisted testing; subagents for security and performance review.",
        ],
    },
    {
        "key": "roof-graph",
        "name": "Roof Graph Extraction",
        "url": "github.com/ramintkml/Roof_Graph_Extraction",
        "match": ("roof graph", "deed asia", "gnn"),
        "tokens": (
            "python",
            "gnn",
            "pytorch",
            "computer vision",
            "3d",
            "scikit-learn",
            "debugging",
            "synthetic",
        ),
        "bullets": [
            "Python pipeline extracting 2D orthogonal and perspective graphs from 3D roof meshes (.obj) using trimesh, shapely, and scikit-learn.",
            "Classified roof edges and visible rooftop blocks; exported bounding boxes, keypoints (CSV), and classified graphs (JSON).",
            "Designed GNN models and trained them on self-created synthetic graph/spatial datasets.",
            "Implemented visual debugging tools and a genetic-algorithm optimizer; 150+ GitHub commits; core engine for Deed Asia roof modeling.",
        ],
    },
]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower())


def match_canonical(proj: dict[str, Any]) -> dict[str, Any] | None:
    blob = _norm(
        " ".join(
            str(proj.get(k) or "")
            for k in ("name", "subtitle", "url", "link", "key")
        )
    )
    for canon in CANONICAL_PROJECTS:
        if canon["key"] in blob.replace(" ", "-"):
            return canon
        if any(m in blob for m in canon["match"]):
            return canon
    return None


def _relevance(canon: dict[str, Any], jd: str) -> int:
    jd_n = _norm(jd)
    score = 0
    for tok in canon["tokens"]:
        if tok in jd_n:
            score += 3
    for m in canon["match"]:
        if m in jd_n:
            score += 5
    return score


def _tailored_bullets(ai_proj: dict[str, Any] | None, canon: dict[str, Any]) -> list[str]:
    if not ai_proj:
        return list(canon["bullets"])
    raw = list(ai_proj.get("bullets") or [])
    out: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("title") or "").strip()
            if text:
                out.append(text)
            for sub in item.get("sub_bullets") or item.get("children") or []:
                s = str(sub).strip()
                if s:
                    out.append(s)
        else:
            s = str(item).strip()
            if s:
                out.append(s)
    if 4 <= len(out) <= 6:
        return out
    if len(out) > 6:
        return out[:6]
    seen = {x.lower() for x in out}
    for b in canon["bullets"]:
        if b.lower() not in seen:
            out.append(b)
            seen.add(b.lower())
        if len(out) >= 5:
            break
    return out[:6] or list(canon["bullets"])[:5]


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
    """Force all canonical projects in; merge AI bullets; reorder by JD."""
    existing = list(resume.get("projects") or [])
    by_key: dict[str, dict[str, Any]] = {}
    unmatched: list[dict[str, Any]] = []
    for proj in existing:
        if not isinstance(proj, dict):
            continue
        canon = match_canonical(proj)
        if canon:
            by_key[canon["key"]] = proj
        else:
            unmatched.append(proj)

    jd = job_text or ""
    ranked = sorted(
        CANONICAL_PROJECTS,
        key=lambda c: (-_relevance(c, jd), c["name"]),
    )
    merged: list[dict[str, Any]] = []
    for canon in ranked:
        ai = by_key.get(canon["key"])
        merged.append(
            {
                "name": canon["name"],
                "subtitle": "",
                "url": canon["url"],
                "bullets": _tailored_bullets(ai, canon),
            }
        )
    # Keep extra truthful projects after the canonical five
    merged.extend(unmatched)
    resume["projects"] = merged
    return resume


def project_markdown_rules() -> str:
    names = "\n".join(
        f"- {p['name']} — {p['url']}" for p in CANONICAL_PROJECTS
    )
    return f"""SELECTED PROJECTS (mandatory on every tailored resume):
Include ALL of these projects, never drop one. Reorder by JD relevance
(closest stack/domain first). Keep the links. Parent bullet = project name + links.
Sub-bullets = 4 or 5 facts (maximum 6) from the base CV (Claim/Bridge JD spellings only).

{names}

Markdown shape:
- Project Name — github/live links
  - Action Verb + tech + outcome (JD-aligned, truthful)
  - ...
"""
