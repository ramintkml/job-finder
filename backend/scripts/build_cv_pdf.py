"""Build data/cv/Ramin_Takmil_CV.pdf from the markdown source."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MD_PATH = ROOT / "data" / "cv" / "Ramin_Takmil_CV.md"
PDF_PATH = ROOT / "data" / "cv" / "Ramin_Takmil_CV.pdf"

MARGIN = 18
BODY_PT = 11.5
CONTACT_PT = 11
ROLE_PT = 12
SECTION_PT = 14
TITLE_PT = 24
SUBTITLE_PT = 12

MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
ROLE_LINE = re.compile(r"^\*\*(.+?)\*\*\s*\|\s*(.+)$")
LABEL_LINE = re.compile(r"^\*\*(.+?):\*\*\s*(.+)$")
PROJECT_LINE = re.compile(r"^\*\*(.+?)\*\*\s*[—–-]\s*(.+)$")


@dataclass
class Block:
    kind: str
    text: str = ""
    title: str = ""
    subtitle: str = ""
    items: list[str] = field(default_factory=list)
    raw: str = ""


def _ascii_safe(text: str) -> str:
    return (
        text.replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2022", "-")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )


def _esc(text: str) -> str:
    return html.escape(_ascii_safe(text))


def _links_to_html(line: str) -> str:
    parts: list[str] = []
    last = 0
    for match in MD_LINK.finditer(line):
        if match.start() > last:
            parts.append(_esc(line[last : match.start()]))
        label = _esc(match.group(1))
        url = html.escape(match.group(2).strip(), quote=True)
        parts.append(f'<a href="{url}">{label}</a>')
        last = match.end()
    if last < len(line):
        parts.append(_esc(line[last:]))
    return "".join(parts)


def _strip_md(line: str) -> str:
    line = line.strip()
    line = re.sub(r"^#+\s*", "", line)
    line = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
    line = re.sub(r"\*(.*?)\*", r"\1", line)
    return _ascii_safe(line.strip())


def parse_cv(lines: list[str]) -> list[Block]:
    blocks: list[Block] = []
    bullet_buf: list[str] = []

    def flush_bullets() -> None:
        if bullet_buf:
            blocks.append(Block(kind="bullets", items=bullet_buf.copy()))
            bullet_buf.clear()

    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped == "---":
            flush_bullets()
            if stripped == "---":
                blocks.append(Block(kind="divider"))
            continue

        if raw.startswith("# "):
            flush_bullets()
            blocks.append(Block(kind="title", text=_strip_md(raw)))
            continue

        if raw.startswith("## "):
            flush_bullets()
            blocks.append(Block(kind="heading", text=_strip_md(raw)))
            continue

        if raw.startswith("- "):
            bullet_buf.append(_strip_md(raw[2:]))
            continue

        flush_bullets()

        if raw.startswith("**") and raw.endswith("**") and "|" not in raw and ":" not in raw[2:]:
            blocks.append(Block(kind="subtitle", text=_strip_md(raw)))
            continue

        if MD_LINK.search(raw):
            blocks.append(Block(kind="contact", raw=raw))
            continue

        role = ROLE_LINE.match(raw.strip())
        if role:
            blocks.append(
                Block(kind="role", title=_ascii_safe(role.group(1)), subtitle=_ascii_safe(role.group(2)))
            )
            continue

        label = LABEL_LINE.match(raw.strip())
        if label:
            blocks.append(
                Block(
                    kind="skill",
                    title=_ascii_safe(label.group(1)),
                    text=_ascii_safe(label.group(2)),
                )
            )
            continue

        project = PROJECT_LINE.match(raw.strip())
        if project:
            blocks.append(
                Block(
                    kind="project",
                    title=_ascii_safe(project.group(1)),
                    text=_ascii_safe(project.group(2)),
                )
            )
            continue

        if raw.startswith("*") and raw.endswith("*") and not raw.startswith("**"):
            blocks.append(Block(kind="footer", text=_strip_md(raw)))
            continue

        if raw.startswith("**") and ":" in raw:
            match = re.match(r"^\*\*(.+?):\*\*\s*(.+)$", raw.strip())
            if match:
                blocks.append(
                    Block(
                        kind="skill",
                        title=_ascii_safe(match.group(1)),
                        text=_ascii_safe(match.group(2)),
                    )
                )
                continue

        blocks.append(Block(kind="paragraph", text=_strip_md(raw)))

    flush_bullets()
    return blocks


class CvPdf:
    BLUE = "#1155cc"
    TEXT = "#222222"
    META = "#555555"

    def __init__(self) -> None:
        from fpdf import FPDF

        self.pdf = FPDF(unit="mm", format="A4")
        self.pdf.set_auto_page_break(auto=True, margin=MARGIN)
        self.pdf.set_margins(MARGIN, MARGIN, MARGIN)
        self.pdf.add_page()

    @classmethod
    def _tag_styles(cls):
        from fpdf.fonts import FontFace, TextStyle
        from fpdf.html import DEFAULT_TAG_STYLES

        styles = dict(DEFAULT_TAG_STYLES)
        styles["a"] = FontFace(color=cls.BLUE, emphasis="UNDERLINE")
        styles["h1"] = TextStyle(
            color=cls.BLUE, font_style="B", font_size_pt=TITLE_PT, t_margin=0, b_margin=0.5
        )
        styles["h2"] = TextStyle(
            color=cls.BLUE, font_style="B", font_size_pt=SECTION_PT, t_margin=2.5, b_margin=0.8
        )
        styles["h3"] = TextStyle(
            color=cls.TEXT, font_style="B", font_size_pt=ROLE_PT, t_margin=2, b_margin=0.5
        )
        styles["p"] = TextStyle(color=cls.TEXT, font_size_pt=BODY_PT, t_margin=0, b_margin=1.2)
        styles["ul"] = TextStyle(t_margin=0.5, b_margin=1)
        styles["li"] = TextStyle(color=cls.TEXT, font_size_pt=BODY_PT, t_margin=0.3, b_margin=1, l_margin=4)
        return styles

    def _block_html(self, block: Block) -> str:
        if block.kind == "divider":
            return ""
        if block.kind == "title":
            return f"<h1>{_esc(block.text)}</h1>"
        if block.kind == "subtitle":
            return f'<p><font size="{int(SUBTITLE_PT)}"><b>{_esc(block.text)}</b></font></p>'
        if block.kind == "contact":
            return f'<p><font size="{int(CONTACT_PT)}">{_links_to_html(block.raw)}</font></p>'
        if block.kind == "heading":
            return f"<h2>{_esc(block.text)}</h2>"
        if block.kind == "paragraph":
            return f"<p>{_esc(block.text)}</p>"
        if block.kind == "role":
            return (
                f"<h3>{_esc(block.title)}"
                f' <font color="{self.META}">| {_esc(block.subtitle)}</font></h3>'
            )
        if block.kind == "skill":
            return f"<p><b>{_esc(block.title)}:</b> {_esc(block.text)}</p>"
        if block.kind == "project":
            return f"<h3>{_esc(block.title)}</h3><p>{_esc(block.text)}</p>"
        if block.kind == "bullets":
            items = "".join(f"<li>{_esc(item)}</li>" for item in block.items)
            return f"<ul>{items}</ul>"
        if block.kind == "footer":
            return f'<p><i><font color="{self.META}">{_esc(block.text)}</font></i></p>'
        return ""

    def render(self, blocks: list[Block]) -> None:
        body = "".join(self._block_html(block) for block in blocks)
        self.pdf.write_html(
            body,
            tag_styles=self._tag_styles(),
            li_prefix_color=self.BLUE,
        )


def build_pdf() -> None:
    try:
        CvPdf  # noqa: F401
    except Exception:
        raise SystemExit("Install fpdf2: pip install fpdf2")

    if not MD_PATH.is_file():
        raise SystemExit(f"Missing {MD_PATH}")

    blocks = parse_cv(MD_PATH.read_text(encoding="utf-8").splitlines())
    doc = CvPdf()
    doc.render(blocks)

    PDF_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc.pdf.output(str(PDF_PATH))
    print(f"Wrote {PDF_PATH} ({doc.pdf.page_no()} page(s))")


if __name__ == "__main__":
    build_pdf()
