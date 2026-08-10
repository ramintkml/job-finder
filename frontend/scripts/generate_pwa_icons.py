"""Generate Career Pilot PWA icons."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1] / "public"
ICONS = ROOT / "icons"
ICONS.mkdir(parents=True, exist_ok=True)

TEAL = (15, 110, 86, 255)  # #0f6e56
TEAL_DARK = (10, 79, 61, 255)  # #0a4f3d
CREAM = (243, 241, 235, 255)  # #f3f1eb
WHITE = (255, 255, 255, 255)

AI_SRC = Path(
    r"C:\Users\Ramin\.cursor\projects\c-Users-Ramin-Development-Linkedin-Job-Finder"
    r"\assets\career-pilot-icon-512.png"
)


def rounded_rect(draw: ImageDraw.ImageDraw, box, radius: int, fill) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def draw_icon(size: int, *, maskable: bool = False) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = int(size * (0.12 if maskable else 0.06))
    radius = int(size * 0.22)
    rounded_rect(d, (pad, pad, size - pad, size - pad), radius, TEAL)

    doc_w = int(size * 0.34)
    doc_h = int(size * 0.42)
    doc_x = (size - doc_w) // 2 - int(size * 0.04)
    doc_y = (size - doc_h) // 2
    doc_r = max(4, int(size * 0.04))
    rounded_rect(d, (doc_x, doc_y, doc_x + doc_w, doc_y + doc_h), doc_r, WHITE)

    lx0 = doc_x + int(doc_w * 0.18)
    lx1 = doc_x + int(doc_w * 0.82)
    for i, yf in enumerate((0.28, 0.42, 0.56, 0.70)):
        y = doc_y + int(doc_h * yf)
        w = lx1 if i < 3 else doc_x + int(doc_w * 0.62)
        d.line([(lx0, y), (w, y)], fill=TEAL, width=max(2, size // 64))

    cx = doc_x + doc_w + int(size * 0.08)
    cy = size // 2
    arm = int(size * 0.12)
    pts = [
        (cx, cy - arm),
        (cx + int(arm * 0.7), cy),
        (cx, cy + arm),
        (cx - int(arm * 0.55), cy),
    ]
    d.polygon(pts, fill=CREAM)
    r = max(2, size // 40)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=TEAL_DARK)
    return img


def ai_usable(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        ai = Image.open(path).convert("RGBA").resize((32, 32))
        pixels = list(ai.getdata())
        greens = sum(1 for r, g, b, a in pixels if a > 200 and g > r and g > 80)
        return greens > 8
    except Exception:
        return False


def main() -> None:
    # Crisp brand-matched geometric icons (matches favicon.svg)
    draw_icon(512).save(ICONS / "icon-512.png", optimize=True)
    draw_icon(192).save(ICONS / "icon-192.png", optimize=True)
    draw_icon(512, maskable=True).save(ICONS / "icon-512-maskable.png", optimize=True)
    print("generated geometric Career Pilot icons")
    for p in sorted(ICONS.glob("icon-*.png")):
        print(p.name, p.stat().st_size)


if __name__ == "__main__":
    main()
