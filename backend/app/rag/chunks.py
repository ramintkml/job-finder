"""Chunk proposal guide and CV text for indexing."""

from __future__ import annotations

import re

from app.config import CV_MD_PATH, GUIDE_PATH

SKIP_THRESHOLD = 65

_SKIP_GUIDE_TITLES = frozenset({
    "How to Use This File",
    "Freelancer.com Platform Rules",
})


def chunk_proposal_guide(content: str | None = None) -> list[dict[str, str]]:
    text = content if content is not None else GUIDE_PATH.read_text(encoding="utf-8")
    chunks: list[dict[str, str]] = []

    sections = re.split(r"\n(?=## )", text)
    for section in sections:
        section = section.strip()
        if not section or len(section) < 40:
            continue
        title_match = re.match(r"^##\s+(.+)", section)
        title = title_match.group(1).strip() if title_match else "Guide"

        if title in _SKIP_GUIDE_TITLES:
            continue

        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", section) if p.strip()]
        for i, para in enumerate(paragraphs):
            if len(para) < 30:
                continue
            chunks.append({
                "id": f"guide:{title}:{i}",
                "text": f"{title}\n{para}",
                "source": "proposal_guide",
                "label": title,
            })

    return chunks


def chunk_cv(content: str | None = None) -> list[dict[str, str]]:
    """Chunk CV markdown (## sections; projects split on bold titles)."""
    if content is None:
        if not CV_MD_PATH.is_file():
            return []
        content = CV_MD_PATH.read_text(encoding="utf-8")
    text = (content or "").strip()
    if not text:
        return []

    chunks: list[dict[str, str]] = []
    sections = re.split(r"\n(?=## )", text)
    for section in sections:
        section = section.strip()
        if not section or len(section) < 40:
            continue
        title_match = re.match(r"^##\s+(.+)", section)
        title = title_match.group(1).strip() if title_match else "CV"
        body = section[title_match.end():].strip() if title_match else section

        # Skip contact/header blocks that are mostly links/phones
        if not title_match and ("@" in section or "linkedin.com" in section.lower()):
            continue

        project_parts = re.split(r"\n(?=\*\*[^*\n]+\*\*)", body)
        if len(project_parts) > 1 and any(
            k in title.lower() for k in ("project", "experience", "work", "employment")
        ):
            for i, part in enumerate(project_parts):
                part = part.strip()
                if len(part) < 40:
                    continue
                bold = re.match(r"^\*\*([^*]+)\*\*", part)
                label = bold.group(1).strip() if bold else f"{title} {i + 1}"
                # Drop trailing links/pipes from bold title for label
                label = re.split(r"\s+[—\-–|]", label, maxsplit=1)[0].strip() or label
                chunks.append({
                    "id": f"cv:{title}:{i}",
                    "text": f"CV — {title}\n{part}",
                    "source": "cv",
                    "label": f"CV: {label}",
                })
            continue

        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body if title_match else section) if p.strip()]
        if not paragraphs and body:
            paragraphs = [body]
        for i, para in enumerate(paragraphs):
            if len(para) < 30:
                continue
            # Skip pure contact lines
            if para.count("http") >= 2 and len(para) < 200:
                continue
            chunks.append({
                "id": f"cv:{title}:{i}",
                "text": f"CV — {title}\n{para}",
                "source": "cv",
                "label": f"CV: {title}",
            })

    return chunks
