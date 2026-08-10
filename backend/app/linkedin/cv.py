"""CV file path and text helpers for LinkedIn applications."""

from __future__ import annotations

from pathlib import Path

from app.config import DATA_DIR, ROOT_DIR
from app.linkedin.settings import LinkedInSettings

DEFAULT_CV_MD = DATA_DIR / "cv" / "Ramin_Takmil_CV.md"
DEFAULT_CV_PDF = DATA_DIR / "cv" / "Ramin_Takmil_CV.pdf"


def resolve_cv_path(cfg: LinkedInSettings | None = None) -> Path | None:
    raw = ""
    if cfg and cfg.cv_file_path.strip():
        raw = cfg.cv_file_path.strip()
    if raw:
        path = Path(raw)
        if not path.is_absolute():
            path = ROOT_DIR / path
        return path if path.is_file() else None
    return DEFAULT_CV_PDF if DEFAULT_CV_PDF.is_file() else None


def load_cv_text(cfg: LinkedInSettings | None = None) -> str:
    if cfg and cfg.cv_text.strip():
        return cfg.cv_text.strip()
    if DEFAULT_CV_MD.is_file():
        return DEFAULT_CV_MD.read_text(encoding="utf-8").strip()
    return ""
