from pathlib import Path

from app.config import ATS_GUIDE_PATH, DATA_DIR

DATA_GUIDE = DATA_DIR / "ats" / "ATS_Friendly_Resume_Guide.md"

ACTION_VERBS = (
    "developed",
    "designed",
    "built",
    "implemented",
    "optimized",
    "automated",
    "deployed",
    "integrated",
    "led",
    "improved",
    "created",
    "delivered",
    "engineered",
    "architected",
    "reduced",
    "increased",
    "launched",
    "migrated",
    "refactored",
    "scaled",
)


def load_ats_guide() -> str:
    for path in (DATA_GUIDE, ATS_GUIDE_PATH):
        if path.exists():
            return path.read_text(encoding="utf-8")
    return (
        "Create ATS-friendly single-column resumes. Use action verbs, "
        "quantify results, match job keywords without stuffing, never fabricate."
    )


def score_band(total: int) -> str:
    if total >= 90:
        return "Excellent"
    if total >= 80:
        return "Good"
    if total >= 70:
        return "Fair"
    return "Needs Improvement"
