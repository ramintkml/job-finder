"""Persian resume → HTML (RTL, B Nazanin) → PDF.

WeasyPrint is preferred (real CSS bidi). Falls back to writing .html alongside
and a best-effort fpdf path if WeasyPrint is unavailable.
"""

from __future__ import annotations

import html
import logging
from pathlib import Path
from typing import Any

from app.ats.fonts import find_bnazanin_font, find_unicode_font
from app.ats.pdf_export import FA_HEADINGS, _join_bits

logger = logging.getLogger(__name__)


def _esc(text: str) -> str:
    return html.escape((text or "").strip(), quote=True)


def resume_to_html_fa(resume: dict[str, Any], *, font_path: Path | None = None) -> str:
    """Build a clean RTL HTML document for Persian resumes."""
    font = font_path or find_bnazanin_font() or find_unicode_font(prefer_persian=True)
    bold = None
    if font and font.is_file():
        cand_bold = font.parent / "BNazanin-Bold.ttf"
        if cand_bold.is_file():
            bold = cand_bold
        else:
            for p in font.parent.glob("*"):
                if (
                    p.suffix.lower() == ".ttf"
                    and "nazan" in p.name.lower()
                    and "bold" in p.name.lower()
                    and "outline" not in p.name.lower()
                ):
                    bold = p
                    break
    font_uri = font.resolve().as_uri() if font and font.is_file() else ""
    bold_uri = bold.resolve().as_uri() if bold and bold.is_file() else font_uri

    h = FA_HEADINGS
    name = _esc(resume.get("full_name") or "Candidate")
    title = _esc(resume.get("professional_title") or "")
    contact = _esc(
        _join_bits(str(resume.get("email") or ""), str(resume.get("phone") or ""))
    )
    links = _esc(
        _join_bits(
            str(resume.get("linkedin") or ""),
            str(resume.get("github") or ""),
            str(resume.get("portfolio") or ""),
            str(resume.get("location") or ""),
        )
    )

    sections: list[str] = []

    def heading(key: str) -> None:
        sections.append(f'<h2 class="sec">{_esc(h.get(key) or key)}</h2>')

    def para(text: str) -> None:
        t = (text or "").strip()
        if t:
            sections.append(f"<p>{_esc(t)}</p>")

    def bullets(items: list) -> None:
        clean = [str(x).strip() for x in (items or []) if str(x).strip()]
        if not clean:
            return
        lis = "".join(f"<li>{_esc(x)}</li>" for x in clean)
        sections.append(f"<ul>{lis}</ul>")

    if resume.get("summary"):
        heading("summary")
        para(str(resume["summary"]))

    skills = resume.get("skills") or {}
    if isinstance(skills, dict) and skills:
        heading("skills")
        for cat, items in skills.items():
            joined = "، ".join(str(x).strip() for x in (items or []) if str(x).strip())
            if not joined:
                continue
            cat_s = str(cat or "").strip()
            if cat_s:
                sections.append(
                    f"<p><strong>{_esc(cat_s)}:</strong> {_esc(joined)}</p>"
                )
            else:
                para(joined)
    elif isinstance(skills, list) and skills:
        heading("skills")
        para("، ".join(str(x) for x in skills if x))

    projects = resume.get("projects") or []
    if projects:
        heading("projects")
        for proj in projects:
            name_p = (proj.get("name") or "").strip()
            sub = (proj.get("subtitle") or "").strip()
            line = f"{name_p} — {sub}" if sub else name_p
            sections.append(f'<p class="role">{_esc(line)}</p>')
            bullets(list(proj.get("bullets") or []))

    additional = resume.get("additional_experience") or []
    if additional:
        heading("additional")
        for block in additional:
            if isinstance(block, str):
                para(block)
                continue
            label = (block.get("title") or block.get("label") or "").strip()
            text = (block.get("text") or block.get("summary") or "").strip()
            if label:
                sections.append(f'<p class="role">{_esc(label)}</p>')
            if text:
                para(text)
            bullets(list(block.get("bullets") or []))

    experience = resume.get("experience") or []
    if experience:
        heading("experience")
        for role in experience:
            left = " - ".join(
                x
                for x in [
                    (role.get("title") or "").strip(),
                    (role.get("company") or "").strip(),
                ]
                if x
            )
            line = _join_bits(
                left,
                (role.get("location") or "").strip(),
                (role.get("dates") or "").strip(),
            )
            sections.append(f'<p class="role">{_esc(line)}</p>')
            bullets(list(role.get("bullets") or []))

    research = resume.get("research") or []
    if isinstance(research, str) and research.strip():
        heading("research")
        para(research.strip())
    elif isinstance(research, list) and research:
        heading("research")
        for item in research:
            if isinstance(item, str):
                para(item)
            else:
                label = (item.get("title") or "").strip()
                text = (item.get("text") or item.get("summary") or "").strip()
                para(f"{label}: {text}" if label and text else (text or label))

    education = resume.get("education") or []
    if education:
        heading("education")
        for edu in education:
            line = _join_bits(
                (edu.get("degree") or "").strip(),
                (edu.get("school") or "").strip(),
                (edu.get("dates") or "").strip(),
            )
            para(line)

    languages = resume.get("languages") or []
    certs = resume.get("certifications") or []
    if languages or certs:
        heading("languages_certs")
        if isinstance(languages, list):
            for lang in languages:
                para(str(lang))
        elif isinstance(languages, str) and languages.strip():
            para(languages.strip())
        for c in certs:
            para(str(c))

    font_face = ""
    if font_uri:
        font_face = f"""
@font-face {{
  font-family: 'BNazanin';
  src: url('{font_uri}') format('truetype');
  font-weight: normal;
  font-style: normal;
}}
@font-face {{
  font-family: 'BNazanin';
  src: url('{bold_uri}') format('truetype');
  font-weight: bold;
  font-style: normal;
}}
"""

    body = "\n".join(sections)
    return f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8"/>
<title>{name}</title>
<style>
{font_face}
@page {{ size: A4; margin: 14mm 16mm; }}
html, body {{
  direction: rtl;
  text-align: right;
  font-family: 'BNazanin', 'B Nazanin', Tahoma, Arial, sans-serif;
  font-size: 11pt;
  line-height: 1.45;
  color: #1a2330;
}}
h1 {{
  font-size: 18pt;
  margin: 0 0 2px 0;
  font-weight: bold;
}}
.subtitle {{
  font-size: 12pt;
  font-weight: bold;
  margin: 0 0 4px 0;
}}
.meta {{
  font-size: 9.5pt;
  color: #5c6775;
  margin: 0 0 2px 0;
}}
h2.sec {{
  font-size: 12pt;
  margin: 14px 0 6px 0;
  padding-bottom: 3px;
  border-bottom: 1px solid #c8c4ba;
  font-weight: bold;
}}
p {{ margin: 0 0 6px 0; }}
p.role {{ font-weight: bold; margin: 8px 0 2px 0; }}
ul {{
  margin: 0 0 8px 0;
  padding: 0 18px 0 0;
  list-style-position: outside;
}}
li {{ margin: 0 0 3px 0; }}
</style>
</head>
<body>
<h1>{name}</h1>
{f'<p class="subtitle">{title}</p>' if title else ''}
{f'<p class="meta">{contact}</p>' if contact else ''}
{f'<p class="meta">{links}</p>' if links else ''}
{body}
</body>
</html>
"""


def html_to_pdf(html_doc: str, path: Path) -> Path:
    """Render HTML to PDF. Prefer WeasyPrint, then Chrome/Edge headless, then Playwright."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    html_path = path.with_suffix(".html")
    html_path.write_text(html_doc, encoding="utf-8")

    try:
        from weasyprint import HTML

        HTML(string=html_doc, base_url=str(path.parent)).write_pdf(str(path))
        if path.is_file() and path.stat().st_size > 1000:
            return path
    except Exception:
        logger.exception("WeasyPrint FA PDF failed; trying Chrome/Edge headless")

    if _chrome_print_to_pdf(html_path, path):
        return path

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.set_content(html_doc, wait_until="load")
            page.pdf(
                path=str(path),
                format="A4",
                margin={
                    "top": "14mm",
                    "bottom": "14mm",
                    "left": "16mm",
                    "right": "16mm",
                },
            )
            browser.close()
        if path.is_file() and path.stat().st_size > 1000:
            return path
    except Exception:
        logger.exception("Playwright FA PDF failed")

    raise RuntimeError(
        "FA PDF via HTML failed (need weasyprint or Chrome/Edge). HTML saved at: "
        + str(html_path)
    )


def _chrome_print_to_pdf(html_path: Path, pdf_path: Path) -> bool:
    import os
    import subprocess

    candidates: list[Path] = []
    for env_key in ("CHROME_PATH", "EDGE_PATH"):
        raw = (os.environ.get(env_key) or "").strip()
        if raw:
            candidates.append(Path(raw))
    candidates.extend(
        [
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
            Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
            Path("/usr/bin/google-chrome"),
            Path("/usr/bin/google-chrome-stable"),
            Path("/usr/bin/chromium"),
            Path("/usr/bin/chromium-browser"),
            Path("/usr/bin/microsoft-edge"),
            Path("/snap/bin/chromium"),
        ]
    )
    exe = next((p for p in candidates if p.is_file()), None)
    if exe is None:
        return False
    try:
        # file URI for local HTML + embedded font paths
        uri = html_path.resolve().as_uri()
        cmd = [
            str(exe),
            "--headless=new",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path.resolve()}",
            uri,
        ]
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if pdf_path.is_file() and pdf_path.stat().st_size > 1000:
            return True
        logger.warning(
            "Chrome print-to-pdf failed exit=%s stderr=%s",
            completed.returncode,
            (completed.stderr or "")[:300],
        )
    except Exception:
        logger.exception("Chrome/Edge headless PDF failed")
    return False


def export_resume_pdf_fa_html(resume: dict[str, Any], path: Path) -> Path:
    font = find_bnazanin_font() or find_unicode_font(prefer_persian=True)
    doc = resume_to_html_fa(resume, font_path=font)
    return html_to_pdf(doc, Path(path))
