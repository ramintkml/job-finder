"""Pure-Python TF-IDF index when chromadb/fastembed are not installed (lean VPS).

Avoids numpy — some VPS images ship a numpy wheel that requires unsupported CPU
features (e.g. X86_V2).
"""

from __future__ import annotations

import json
import logging
import math
import re

from app.config import DATA_DIR

logger = logging.getLogger(__name__)

INDEX_PATH = DATA_DIR / "rag_lean_index.json"

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#./-]{1,}", re.I)

_cache: dict | None = None


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) > 1]


def clear() -> None:
    global _cache
    _cache = None
    if INDEX_PATH.exists():
        INDEX_PATH.unlink()


def count() -> int:
    data = _load()
    return int(data["n"]) if data else 0


def _load() -> dict | None:
    global _cache
    if _cache is not None:
        return _cache
    if not INDEX_PATH.is_file():
        return None
    try:
        raw = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        vocab: list[str] = raw["vocab"]
        term_to_idx = {t: i for i, t in enumerate(vocab)}
        _cache = {
            "n": len(raw["ids"]),
            "vectors": raw["vectors"],
            "idf": raw["idf"],
            "vocab": vocab,
            "term_to_idx": term_to_idx,
            "ids": raw["ids"],
            "documents": raw["documents"],
            "labels": raw["labels"],
            "sources": raw["sources"],
        }
        return _cache
    except Exception:
        logger.exception("Failed to load lean RAG index")
        return None


def _vectorize(tokens: list[str], term_to_idx: dict[str, int], idf: list[float]) -> list[float]:
    dim = len(term_to_idx)
    vec = [0.0] * dim
    if not tokens:
        return vec
    counts: dict[str, int] = {}
    for t in tokens:
        if t in term_to_idx:
            counts[t] = counts.get(t, 0) + 1
    if not counts:
        return vec
    length = len(tokens)
    for t, c in counts.items():
        j = term_to_idx[t]
        vec[j] = (c / length) * idf[j]
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def upsert(chunks: list[dict[str, str]]) -> int:
    global _cache
    if not chunks:
        return 0

    docs_tokens = [_tokenize(c["text"]) for c in chunks]
    vocab = sorted({t for toks in docs_tokens for t in toks})
    if not vocab:
        raise ValueError("Proposal guide chunks produced no indexable tokens.")

    term_to_idx = {t: i for i, t in enumerate(vocab)}
    n = len(chunks)
    dim = len(vocab)
    df = [0.0] * dim
    for toks in docs_tokens:
        for t in set(toks):
            df[term_to_idx[t]] += 1
    idf = [math.log((n + 1.0) / (df[i] + 1.0)) + 1.0 for i in range(dim)]

    vectors = [_vectorize(toks, term_to_idx, idf) for toks in docs_tokens]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(
        json.dumps(
            {
                "vocab": vocab,
                "idf": idf,
                "vectors": vectors,
                "ids": [c["id"] for c in chunks],
                "documents": [c["text"] for c in chunks],
                "labels": [c.get("label", "")[:200] for c in chunks],
                "sources": [c.get("source", "") for c in chunks],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _cache = None
    logger.info("Lean RAG index built: %s chunks, %s terms", n, dim)
    return n


def query(text: str, *, n_results: int = 5) -> list[dict]:
    data = _load()
    if not data or data["n"] == 0:
        return []

    q = _vectorize(_tokenize(text), data["term_to_idx"], data["idf"])
    if not any(q):
        return []

    scored = [(_dot(data["vectors"][i], q), i) for i in range(data["n"])]
    scored.sort(key=lambda x: x[0], reverse=True)

    out: list[dict] = []
    for sim, i in scored[:n_results]:
        if sim <= 0:
            continue
        out.append(
            {
                "id": data["ids"][i],
                "similarity": max(0.0, min(1.0, float(sim))),
                "label": data["labels"][i],
                "source": data["sources"][i],
                "text": data["documents"][i],
            }
        )
    return out
