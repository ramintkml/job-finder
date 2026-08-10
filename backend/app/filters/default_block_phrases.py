"""Default phrases that block a project before RAG matching."""

DEFAULT_BLOCK_PHRASES = [
    "data entry",
    "pdf to excel",
    "pdf to ecxel",
    "pdf to word",
    "pdf to csv",
    "edit text",
    "list creation",
    "typing",
    "listing",
]

ALLOWED_CURRENCIES = frozenset({"USD", "EUR", "GBP", "CAD", "AUD", "HKD"})
