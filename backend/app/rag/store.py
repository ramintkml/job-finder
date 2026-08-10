"""Vector store for profile knowledge (ChromaDB or lean numpy TF-IDF on VPS)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.config import CHROMA_PATH, DATA_DIR

logger = logging.getLogger(__name__)

COLLECTION_NAME = "profile_knowledge"

try:
    import chromadb

    _CHROMA_OK = True
except ImportError:
    chromadb = None  # type: ignore
    _CHROMA_OK = False
    logger.info("chromadb not installed — using lean numpy TF-IDF index")


def chroma_available() -> bool:
    return _CHROMA_OK


def backend_name() -> str:
    if _CHROMA_OK:
        return "chroma"
    return "lean"


def _client():
    if not _CHROMA_OK:
        raise RuntimeError("chromadb is not installed")
    CHROMA_PATH.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(CHROMA_PATH))


def get_collection():
    return _client().get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def collection_count() -> int:
    if _CHROMA_OK:
        try:
            return get_collection().count()
        except Exception:
            return 0
    from app.rag import lean_store

    return lean_store.count()


def clear_collection() -> None:
    if _CHROMA_OK:
        client = _client()
        try:
            client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
        return
    from app.rag import lean_store

    lean_store.clear()


def upsert_chunks(chunks: list[dict[str, str]]) -> int:
    if not chunks:
        return 0
    if _CHROMA_OK:
        from app.rag.embedder import embed_texts

        col = get_collection()
        ids = [c["id"] for c in chunks]
        documents = [c["text"] for c in chunks]
        embeddings = embed_texts(documents)
        metadatas = [
            {"source": c["source"], "label": c.get("label", "")[:200]}
            for c in chunks
        ]
        col.upsert(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)
        return len(chunks)

    from app.rag import lean_store

    return lean_store.upsert(chunks)


def query_project(text: str, *, n_results: int = 5) -> list[dict]:
    if _CHROMA_OK:
        col = get_collection()
        if col.count() == 0:
            return []
        from app.rag.embedder import embed_texts

        embedding = embed_texts([text])[0]
        result = col.query(query_embeddings=[embedding], n_results=min(n_results, col.count()))
        out: list[dict] = []
        if not result or not result.get("ids"):
            return out
        for i, doc_id in enumerate(result["ids"][0]):
            distance = result["distances"][0][i] if result.get("distances") else 1.0
            similarity = max(0.0, 1.0 - float(distance))
            meta = (result.get("metadatas") or [[{}]])[0][i] or {}
            out.append({
                "id": doc_id,
                "similarity": similarity,
                "label": meta.get("label", ""),
                "source": meta.get("source", ""),
                "text": (result.get("documents") or [[""]])[0][i] or "",
            })
        return out

    from app.rag import lean_store

    return lean_store.query(text, n_results=n_results)


def write_index_meta(*, chunk_count: int, guide_count: int, cv_count: int = 0) -> None:
    meta_path = DATA_DIR / "rag_index_meta.txt"
    meta_path.write_text(
        f"indexed_at={datetime.now(timezone.utc).isoformat()}\n"
        f"chunks={chunk_count}\n"
        f"guide={guide_count}\n"
        f"cv={cv_count}\n"
        f"backend={backend_name()}\n",
        encoding="utf-8",
    )


def read_index_meta() -> dict[str, str]:
    meta_path = DATA_DIR / "rag_index_meta.txt"
    if not meta_path.exists():
        return {}
    data: dict[str, str] = {}
    for line in meta_path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
    return data
