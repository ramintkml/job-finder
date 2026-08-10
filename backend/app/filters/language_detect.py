"""Language check stub — lingua package intentionally not used for now.

When English is required by pre-match filters, text is accepted without offline
detection. Re-enable lingua later by restoring the previous detector.
"""

from __future__ import annotations


def check_english(text: str) -> tuple[bool, str]:
    """
    Return (is_english, detail).

    detail is empty when English; otherwise a short reason for skip logs/UI.
    """
    sample = (text or "").strip()
    if not sample:
        return False, "empty text"
    # No offline detector installed — do not reject postings on language alone.
    return True, ""
