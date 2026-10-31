"""Neural embeddings are retired; retrieval uses the deterministic lean store."""


def get_embedder():
    raise RuntimeError("Neural embeddings are retired; use app.rag.lean_store")


def embed_texts(texts):
    raise RuntimeError("Neural embeddings are retired; use app.rag.lean_store")
