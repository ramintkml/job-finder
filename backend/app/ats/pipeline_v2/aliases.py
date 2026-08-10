"""Alias packs: evidence matching only — scored/written form stays JD spelling."""

from __future__ import annotations

# Lowercase key → alias list (lowercase). Keys are canonical phrases.
ALIAS_PACK: dict[str, list[str]] = {
    "machine learning": ["ml", "machine-learning", "deep learning", "dl"],
    "deep learning": ["dl", "neural networks", "neural network"],
    "computer vision": ["cv", "image processing", "vision"],
    "natural language processing": ["nlp", "text processing"],
    "large language models": ["llm", "llms", "genai", "generative ai"],
    "llm": ["llms", "large language model", "large language models"],
    "ci/cd": [
        "cicd",
        "ci cd",
        "continuous integration",
        "continuous delivery",
        "continuous deployment",
    ],
    "continuous integration": ["ci", "ci/cd", "cicd"],
    "continuous delivery": ["cd", "ci/cd", "cicd"],
    "version control": ["git", "github", "versioning", "source control"],
    "versioning": ["git", "github", "version control"],
    "rest api": ["restful", "restful api", "rest apis", "restful apis"],
    "restful": ["rest", "rest api", "restful api"],
    "api design": ["api architecture", "rest api design"],
    "software engineering": ["software development", "clean code", "software architecture"],
    "data pipelines": ["etl", "data pipeline", "end-to-end data pipelines"],
    "feature engineering": ["feature extraction", "features"],
    "model optimization": ["optimize models", "model tuning"],
    "hyperparameter optimization": ["hyperparameter tuning", "hpo", "genetic-algorithm"],
    "graph neural networks": ["gnn", "gnns", "graph neural network"],
    "pytorch": ["torch"],
    "tensorflow": ["tf", "keras"],
    "scikit-learn": ["sklearn", "scikit learn"],
    "fastapi": ["fast api"],
    "docker": ["containerized", "containers", "containerisation", "containerization"],
    "github": ["git hub"],
    "python": ["py"],
}


def aliases_for(jd_term: str) -> list[str]:
    """Return alias list for a JD term (excluding the term itself)."""
    key = (jd_term or "").strip().lower()
    if not key:
        return []
    found: list[str] = []
    if key in ALIAS_PACK:
        found.extend(ALIAS_PACK[key])
    # Also match if jd_term is itself an alias of a pack key
    for canon, aliases in ALIAS_PACK.items():
        if key == canon or key in aliases:
            found.append(canon)
            found.extend(aliases)
    # Dedupe, drop self
    out: list[str] = []
    seen = {key}
    for a in found:
        a = a.strip().lower()
        if not a or a in seen:
            continue
        seen.add(a)
        out.append(a)
    return out


# Rough routing into Ramin Takmil skill categories
CATEGORY_HINTS: list[tuple[str, tuple[str, ...]]] = [
    (
        "AI & ML",
        (
            "machine learning",
            "deep learning",
            "ml",
            "llm",
            "rag",
            "pytorch",
            "tensorflow",
            "computer vision",
            "nlp",
            "gnn",
            "scikit",
            "model",
            "feature engineering",
            "hyperparameter",
            "neural",
            "ai",
            "genai",
        ),
    ),
    (
        "Development",
        (
            "python",
            "typescript",
            "javascript",
            "api",
            "rest",
            "graphql",
            "flask",
            "fastapi",
            "nestjs",
            "backend",
            "frontend",
            "full-stack",
            "fullstack",
            "software engineering",
            "software development",
        ),
    ),
    (
        "Frameworks & tools",
        (
            "docker",
            "ci/cd",
            "cicd",
            "git",
            "github",
            "version",
            "kubernetes",
            "k8s",
            "aws",
            "azure",
            "react",
            "next.js",
            "nextjs",
            "chromadb",
            "numpy",
            "pandas",
            "opencv",
        ),
    ),
    (
        "Focus areas",
        (
            "automation",
            "workflow",
            "rtl",
            "pipeline",
            "decision",
            "medical",
            "3d",
            "geometry",
        ),
    ),
]


def prefer_skills_category(jd_term: str, existing_categories: list[str] | None = None) -> str:
    """Pick an existing-style category name for hard-insert merge."""
    term_l = (jd_term or "").lower()
    existing = [c for c in (existing_categories or []) if c]
    # Prefer matching an existing category by hint
    for cat, hints in CATEGORY_HINTS:
        if any(h in term_l for h in hints):
            for ex in existing:
                if ex.lower() == cat.lower() or cat.lower() in ex.lower() or ex.lower() in cat.lower():
                    return ex
            # If resume already has a close name, use first existing AI-like cat
            for ex in existing:
                el = ex.lower()
                if cat == "AI & ML" and ("ai" in el or "ml" in el or "machine" in el):
                    return ex
                if cat == "Development" and ("dev" in el or "engineer" in el or "api" in el):
                    return ex
                if cat == "Frameworks & tools" and ("tool" in el or "framework" in el):
                    return ex
                if cat == "Focus areas" and ("focus" in el or "area" in el):
                    return ex
            return cat if not existing else (existing[0] if cat not in {e for e in existing} else cat)
    # Fallback: first existing category, else Frameworks & tools
    if existing:
        return existing[0]
    return "Frameworks & tools"
