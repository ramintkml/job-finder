"""One-off: rename Job Search applications folders to short titles."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.ats.naming import folder_slug, sanitize_job_title

root = Path(r"C:\Users\Ramin\Desktop\Job Search\applications")
TS_RE = re.compile(r"_(\d{8}-\d{6})$")
GENERIC = {
    "about the role",
    "job description",
    "responsibilities",
    "target role",
    "role",
    "unknown",
    "n/a",
}


def _clean_company(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    s = re.split(r"[(\[]", s, 1)[0].strip()
    s = sanitize_job_title(s, max_len=24)
    if s.lower() in GENERIC or s.lower().startswith("unknown"):
        return ""
    return s


def _is_generic_title(t: str) -> bool:
    tl = (t or "").strip().lower()
    if not tl or tl in GENERIC:
        return True
    if tl.startswith("in the story of"):
        return True
    if tl.startswith("about the role") and "(" not in tl:
        return True
    return False


def _from_posting(text: str) -> tuple[str, str]:
    title = ""
    company = ""
    fm: dict[str, str] = {}
    if text.lstrip().startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    fm[k.strip().lower()] = v.strip().strip('"').strip("'")

    for key in ("inferred_role", "role"):
        if fm.get(key):
            title = fm[key]
            break
    if fm.get("inferred_employer"):
        company = fm["inferred_employer"]
    elif fm.get("company"):
        company = fm["company"]

    m = re.search(r"(?im)\*\*Title:\*\*\s*(.+)$", text)
    if m:
        cand = m.group(1).strip()
        pm = re.search(r"\(([^)]+)\)\s*$", cand)
        if pm and not _is_generic_title(pm.group(1)):
            title = pm.group(1).strip()
        elif not _is_generic_title(cand):
            title = cand

    m = re.search(r"(?im)^\|\s*Title\s*\|\s*(.+?)\s*\|", text)
    if m:
        cand = m.group(1).strip()
        pm = re.search(r"\(([^)]+)\)", cand)
        if pm and not _is_generic_title(pm.group(1)):
            title = pm.group(1).strip()
        elif not _is_generic_title(cand.split("(")[0]):
            title = re.sub(r"\(.*?\)", "", cand).strip()

    m = re.search(r"(?m)^#\s+(.+)$", text)
    if m:
        cand = m.group(1).strip()
        if not _is_generic_title(cand.split("—")[0].split("–")[0].strip()):
            cand = re.split(r"[—–]\s*Unknown", cand, 1)[0].strip()
            if not _is_generic_title(cand):
                title = cand

    if _is_generic_title(title) or not title:
        if re.search(r"snappfood", text, re.I):
            company = company or "Snappfood"
            if re.search(r"machine learning engineer|ml engineer|mlops", text, re.I):
                title = "Machine Learning Engineer"
        if re.search(r"prompt engineer", text, re.I) and _is_generic_title(title):
            title = "Prompt Engineer"
        if (
            re.search(r"backend engineer.*python|python.*backend engineer", text, re.I)
            and _is_generic_title(title)
        ):
            title = "Backend Engineer Python"
        if re.search(r"full-?stack software engineer", text, re.I) and _is_generic_title(title):
            title = "Full-Stack Software Engineer"
        if re.search(r"customer engineer", text, re.I) and _is_generic_title(title):
            title = "Customer Engineer"

    return title, company


def extract_meta(folder: Path) -> tuple[str, str, str]:
    title = ""
    company = ""
    stamp = ""
    m = TS_RE.search(folder.name)
    if m:
        stamp = m.group(1)

    rj = folder / "RESULT.json"
    if rj.is_file():
        try:
            data = json.loads(rj.read_text(encoding="utf-8"))
            title = str(data.get("short_title") or data.get("title") or "").strip()
            company = str(data.get("company") or "").strip()
        except Exception:
            pass

    posting = folder / "posting.md"
    if posting.is_file():
        pt, pc = _from_posting(posting.read_text(encoding="utf-8", errors="replace"))
        if pt and (_is_generic_title(title) or not title):
            title = pt
        if pc and (
            not company or company.lower() in GENERIC or company.lower().startswith("unknown")
        ):
            company = pc

    if _is_generic_title(title) or not title:
        base = folder.name[: m.start()] if m else folder.name
        parts = [p for p in base.split("_") if p]
        if parts and parts[0] == "company":
            parts = parts[1:]
        if len(parts) >= 2:
            company = company or parts[0].replace("-", " ")
            title = " ".join(parts[1:]).replace("-", " ")
        elif parts:
            title = parts[0].replace("-", " ")

    title = sanitize_job_title(title, max_len=40)
    company = _clean_company(company)
    if _is_generic_title(title):
        title = "Target Role"
    return title, company, stamp


def main() -> None:
    renames: list[tuple[str, str]] = []
    used = {p.name.lower() for p in root.iterdir() if p.is_dir()}

    for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")):
        title, company, stamp = extract_meta(folder)
        slug = folder_slug(title, company, max_len=48)
        if not stamp:
            stamp = "legacy"
        new_name = f"{slug}_{stamp}"
        n = 2
        while new_name.lower() in used and new_name.lower() != folder.name.lower():
            new_name = f"{slug}-{n}_{stamp}"
            n += 1
        if new_name != folder.name:
            dest = root / new_name
            print(f"{folder.name}\n  -> {new_name}  [{company} | {title}]")
            folder.rename(dest)
            used.discard(folder.name.lower())
            used.add(new_name.lower())
            meta = dest / "_folder_meta.json"
            meta.write_text(
                json.dumps(
                    {"short_title": title, "company": company, "old_name": folder.name},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            renames.append((folder.name, str(dest)))
        else:
            print(f"KEEP {folder.name}  [{company} | {title}]")

    map_path = root / "_rename_map.json"
    map_path.write_text(
        json.dumps([{"old": a, "new": b} for a, b in renames], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nRenamed {len(renames)} folders")
    print(f"Map: {map_path}")


if __name__ == "__main__":
    main()
