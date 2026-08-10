"""App-written improvement guide from ATS score gaps (sent to AI on regenerate)."""

from __future__ import annotations

import json
from typing import Any

CATEGORY_LABELS = {
    "formatting": "Formatting",
    "keyword_match": "Keyword match",
    "achievements": "Achievements",
    "action_verbs": "Action verbs",
    "readability": "Readability",
    "skills": "Skills",
    "projects": "Projects",
    "grammar": "Grammar",
}


def _weak_categories(scoring: dict[str, Any], *, ratio_threshold: float = 0.85) -> list[dict]:
    cats = scoring.get("categories") or {}
    maxes = scoring.get("max_scores") or {}
    weak: list[dict] = []
    for key, max_score in maxes.items():
        max_score = int(max_score or 0)
        if max_score <= 0:
            continue
        val = int(cats.get(key) or 0)
        ratio = val / max_score
        if ratio < ratio_threshold:
            weak.append(
                {
                    "category": key,
                    "label": CATEGORY_LABELS.get(key, key),
                    "score": val,
                    "max": max_score,
                    "deficit": max_score - val,
                }
            )
    weak.sort(key=lambda x: (-x["deficit"], x["category"]))
    return weak


def _category_instruction(key: str, scoring: dict[str, Any]) -> str:
    missing = scoring.get("keyword_missing") or []
    if key == "formatting":
        return (
            "Keep a single-column DOCX layout. Do not use tables, text boxes, "
            "headers, footers, or multi-column designs."
        )
    if key == "keyword_match":
        if missing:
            listed = ", ".join(str(k) for k in missing[:15])
            return (
                f"Where truthful based on the base CV, weave in these missing job terms "
                f"(prefer exact wording): {listed}. "
                "Skip any term you cannot honestly claim."
            )
        return (
            "Mirror exact wording from the job description for skills and tools "
            "already supported by the base CV."
        )
    if key == "achievements":
        return (
            "Add measurable results to more bullets (percentages, time saved, scale, "
            "latency, users, revenue impact). Only use metrics supported by the base CV; "
            "do not invent numbers."
        )
    if key == "action_verbs":
        return (
            "Start every bullet with a strong action verb "
            "(Built, Led, Designed, Implemented, Optimized, Deployed, Automated…)."
        )
    if key == "readability":
        return (
            "Shorten long bullets to one idea each (ideally under ~25 words). "
            "Avoid multi-clause 'and…and…' sentences. Do not use prose description "
            "fields under roles — use bullets only."
        )
    if key == "skills":
        return (
            "Group skills into clear categories that match the job "
            "(e.g. Languages, Frameworks, Cloud, AI/LLM)."
        )
    if key == "projects":
        return (
            "Include 1–2 relevant projects with tech + outcome bullets drawn from the base CV."
        )
    if key == "grammar":
        return (
            "Use consistent past/present tense and consistent end punctuation across all bullets."
        )
    return "Improve this category using the ATS guide without inventing experience."


def build_improvement_guide(scoring: dict[str, Any]) -> dict[str, Any]:
    """Build deterministic How-to-improve text from scoring (no AI)."""
    weak = _weak_categories(scoring)
    total = scoring.get("total_score")
    band = scoring.get("band") or "—"
    missing = scoring.get("keyword_missing") or []

    if not weak:
        summary = (
            f"Score {total}/100 ({band}) looks strong. Only tweak wording if the job "
            "emphasizes different terms you already have."
        )
        guide_lines = [
            summary,
            "Do not rewrite sections that already score well.",
            "Never invent employers, degrees, dates, metrics, or skills.",
        ]
        return {
            "summary": summary,
            "priority_tips": [],
            "category_tips": {},
            "guide_text": "\n".join(guide_lines),
        }

    priority: list[dict] = []
    category_tips: dict[str, str] = {}
    for item in weak:
        key = item["category"]
        tip = _category_instruction(key, scoring)
        category_tips[key] = tip
        priority.append(
            {
                "category": key,
                "tip": tip,
                "why": f"Scored {item['score']}/{item['max']} — {item['deficit']} points below max",
                "example_fix": None,
            }
        )

    top = ", ".join(p["label"] for p in weak[:3])
    summary = (
        f"Score {total}/100 ({band}). Highest-impact fixes: {top}. "
        "Apply only truthful changes from the base CV."
    )

    guide_lines = [
        "HOW TO IMPROVE THIS RESUME (app-generated from ATS scores — follow these on regenerate):",
        summary,
        f"Target: raise total toward ≥80. Current categories: "
        f"{json.dumps(scoring.get('categories') or {}, ensure_ascii=False)}",
    ]
    if missing:
        guide_lines.append(
            "Missing keywords (add only if truthful): " + ", ".join(str(k) for k in missing[:20])
        )
    guide_lines.append("Priority fixes (ordered by score deficit):")
    for i, item in enumerate(weak, 1):
        guide_lines.append(
            f"{i}. [{item['label']}] {item['score']}/{item['max']} — "
            f"{_category_instruction(item['category'], scoring)}"
        )
    guide_lines.extend(
        [
            "Rules:",
            "- Fix the weak categories above; do not blindly rewrite strong sections.",
            "- Never invent employers, degrees, dates, metrics, or skills not in the base CV.",
            "- Prefer rephrase, reorder, and emphasize over fabrication.",
        ]
    )

    return {
        "summary": summary,
        "priority_tips": priority[:8],
        "category_tips": category_tips,
        "guide_text": "\n".join(guide_lines),
    }


def format_guidance_for_tailor(tips: dict[str, Any] | None, scoring: dict[str, Any] | None) -> str:
    """Text block injected into regenerate prompts."""
    if tips and tips.get("guide_text"):
        return str(tips["guide_text"])
    if not tips and not scoring:
        return ""
    # Rebuild from scoring if stored tips lack guide_text (older rows)
    if scoring:
        rebuilt = build_improvement_guide(
            {
                **scoring,
                "keyword_missing": scoring.get("keyword_missing") or [],
                "keyword_matched": scoring.get("keyword_matched") or [],
            }
        )
        return rebuilt["guide_text"]
    return ""
