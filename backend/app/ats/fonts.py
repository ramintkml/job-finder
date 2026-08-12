"""Locate fonts that can render Latin + Persian for DOCX/PDF export."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

_BUNDLED = Path(__file__).resolve().parent / "fonts"

# Persian-capable fonts (FA PDF/DOCX). Never use these for English PDFs —
# B Nazanin subsets often omit/break Latin glyphs under fpdf Identity-H.
_PERSIAN_CANDIDATES = (
    _BUNDLED / "BNazanin.ttf",
    _BUNDLED / "B Nazanin.ttf",
    Path(r"C:\Windows\Fonts\B Nazanin.ttf"),
    Path(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Fonts\B Nazanin_YasDL.com.ttf")),
    Path(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Fonts\B Nazanin.ttf")),
    Path("/usr/local/share/fonts/BNazanin.ttf"),
    _BUNDLED / "Vazirmatn-Regular.ttf",
    _BUNDLED / "Vazirmatn.ttf",
    Path(r"C:\Windows\Fonts\vazirmatn.ttf"),
    Path("/usr/share/fonts/truetype/vazirmatn/Vazirmatn-Regular.ttf"),
    Path("/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf"),
    _BUNDLED / "Tahoma.ttf",
    Path(r"C:\Windows\Fonts\tahoma.ttf"),
)

# Latin-first fonts for English PDF (Calibri/Arial/DejaVu).
_LATIN_CANDIDATES = (
    _BUNDLED / "Calibri.ttf",
    Path(r"C:\Windows\Fonts\calibri.ttf"),
    _BUNDLED / "Arial.ttf",
    Path(r"C:\Windows\Fonts\arial.ttf"),
    _BUNDLED / "DejaVuSans.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    _BUNDLED / "Tahoma.ttf",
    Path(r"C:\Windows\Fonts\tahoma.ttf"),
)

_CANDIDATES = _PERSIAN_CANDIDATES + _LATIN_CANDIDATES


def _is_persian_font_name(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in ("nazan", "vazir", "naskh", "arabic", "noto sans arabic"))


@lru_cache(maxsize=4)
def find_bnazanin_font() -> Path | None:
    env = (os.environ.get("ATS_FA_FONT") or "").strip()
    if env:
        p = Path(env)
        if p.is_file() and "nazan" in p.name.lower():
            return p
    for path in _PERSIAN_CANDIDATES:
        if path.is_file() and "nazan" in path.name.lower():
            return path
    # Broader search in bundled + local fonts dirs
    for folder in (
        _BUNDLED,
        Path(r"C:\Windows\Fonts"),
        Path(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Fonts")),
    ):
        if not folder.is_dir():
            continue
        for p in folder.glob("*"):
            if p.suffix.lower() in {".ttf", ".otf"} and "nazan" in p.name.lower():
                if "bold" in p.name.lower() or "outline" in p.name.lower():
                    continue
                return p
    return None


@lru_cache(maxsize=4)
def find_latin_font() -> Path | None:
    """TTF for English PDFs — never B Nazanin / Arabic-script fonts."""
    env = (os.environ.get("ATS_EN_FONT") or os.environ.get("ATS_UNICODE_FONT") or "").strip()
    if env:
        p = Path(env)
        if p.is_file() and not _is_persian_font_name(p.name):
            return p
    for path in _LATIN_CANDIDATES:
        if path.is_file() and not _is_persian_font_name(path.name):
            return path
    return None


@lru_cache(maxsize=4)
def find_unicode_font(*, prefer_persian: bool = False) -> Path | None:
    """Return a TTF path usable for PDF / DOCX family hint, or None if none found."""
    if not prefer_persian:
        latin = find_latin_font()
        if latin is not None:
            return latin
        # Last resort: Helvetica built-in (caller may pass None)
        return None

    # FA / RTL path only — ATS_FA_FONT is intentionally ignored for EN.
    env = (os.environ.get("ATS_FA_FONT") or "").strip()
    if env:
        p = Path(env)
        if p.is_file():
            return p

    bn = find_bnazanin_font()
    if bn is not None:
        return bn

    for path in _PERSIAN_CANDIDATES:
        if path.is_file():
            return path
    return find_latin_font()


def font_family_name(path: Path | None, *, fallback: str = "B Nazanin") -> str:
    """Word-friendly family name guess from TTF filename."""
    if path is None:
        return fallback
    stem = path.stem.lower().replace("_", " ")
    if "nazan" in stem:
        return "B Nazanin"
    if "vazir" in stem:
        return "Vazirmatn"
    if "tahoma" in stem:
        return "Tahoma"
    if "arial" in stem:
        return "Arial"
    if "calibri" in stem:
        return "Calibri"
    if "dejavu" in stem:
        return "DejaVu Sans"
    if "noto" in stem and "naskh" in stem:
        return "Noto Naskh Arabic"
    if "noto" in stem and "arabic" in stem:
        return "Noto Sans Arabic"
    if "liberation" in stem:
        return "Liberation Sans"
    return path.stem
