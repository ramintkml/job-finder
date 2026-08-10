"""Fix mis-renamed application folders using old names from _rename_map.json."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.ats.naming import folder_slug, sanitize_job_title

root = Path(r"C:\Users\Ramin\Desktop\Job Search\applications")
TS_RE = re.compile(r"_(\d{8}-\d{6})$")

# Prefer title/company from the pre-rename folder slug when heuristic polluted titles.
# old base (without timestamp) -> (company, title)
FROM_OLD: dict[str, tuple[str, str]] = {
    "ampstek_remote-job-ai-engineer-need-usc": ("Ampstek", "AI Engineer"),
    "coreai-consulting_ai-engineer-agentic-ai": ("CoreAi Consulting", "AI Engineer Agentic AI"),
    "lifescience-logistics_ai-engineer": ("LifeScience Logistics", "AI Engineer"),
    "mastech-digital_gen-ai-and-agentic-ai-engineer": (
        "Mastech Digital",
        "Gen AI and Agentic AI Engineer",
    ),
    "panasonic-automotive-north-america_senior-ai-full-stack-engineer": (
        "Panasonic Automotive",
        "Senior AI Full Stack Engineer",
    ),
    "the-judge-group_prompt-engineer": ("The Judge Group", "Prompt Engineer"),
    "talent-forge-group_ai-engineer": ("Talent Forge Group", "AI Engineer"),
    "jobright-ai_prompt-engineer-early-career-canada": ("Jobright.ai", "Prompt Engineer"),
    "lumenalta_ai-engineer-remote": ("Lumenalta", "AI Engineer Remote"),
}

# Manual fixes for folders that never had a good slug
MANUAL: dict[str, tuple[str, str]] = {
    # current folder name (without needing exact) matched by stamp or startswith
}


def old_base(old_name: str) -> tuple[str, str]:
    m = TS_RE.search(old_name)
    stamp = m.group(1) if m else ""
    base = old_name[: m.start()] if m else old_name
    return base, stamp


def is_bad_title(t: str) -> bool:
    tl = (t or "").lower()
    return any(
        x in tl
        for x in (
            "https",
            "linkedin.com",
            "about the role",
            "posted as",
            "posting body",
            "job description",
            "responsibilities",
            "in the story of",
        )
    )


def title_from_posting(text: str) -> tuple[str, str]:
    title, company = "", ""
    fm: dict[str, str] = {}
    if text.lstrip().startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    fm[k.strip().lower()] = v.strip().strip('"').strip("'")
    title = fm.get("inferred_role") or fm.get("role") or ""
    company = fm.get("inferred_employer") or fm.get("company") or ""

    m = re.search(r"(?im)\*\*Title:\*\*\s*(.+)$", text)
    if m:
        cand = m.group(1).strip()
        pm = re.search(r"\(([^)]+)\)\s*$", cand)
        pick = pm.group(1).strip() if pm else cand
        if pick and not is_bad_title(pick) and pick.lower() not in {"about the role", "role"}:
            title = pick

    m = re.search(r"(?im)^\|\s*Title\s*\|\s*(.+?)\s*\|", text)
    if m:
        cand = m.group(1).strip()
        pm = re.search(r"\(([^)]+)\)", cand)
        pick = pm.group(1).strip() if pm else re.sub(r"\(.*?\)", "", cand).strip()
        if pick and not is_bad_title(pick):
            title = pick

    # First meaningful H1 that looks like a job title
    for m in re.finditer(r"(?m)^#\s+(.+)$", text):
        cand = m.group(1).strip()
        cand = re.split(r"[—–]", cand, maxsplit=1)[0].strip()
        if cand and not is_bad_title(cand) and len(cand) < 80:
            if re.search(
                r"engineer|developer|scientist|architect|analyst|manager|lead|specialist",
                cand,
                re.I,
            ):
                title = cand
                break

    # Company from "**Company:**" or similar
    m = re.search(r"(?im)\*\*Company:\*\*\s*(.+)$", text)
    if m:
        company = company or m.group(1).strip()
    m = re.search(r"(?im)^\|\s*Company\s*\|\s*(.+?)\s*\|", text)
    if m:
        company = company or m.group(1).strip()

    return title, company


def main() -> None:
    map_path = root / "_rename_map.json"
    rename_map = json.loads(map_path.read_text(encoding="utf-8"))
    # new_path -> old_name
    by_new: dict[str, str] = {}
    for row in rename_map:
        by_new[Path(row["new"]).name] = row["old"]

    used = {p.name.lower() for p in root.iterdir() if p.is_dir()}
    fixed: list[tuple[str, str]] = []

    for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")):
        old = by_new.get(folder.name)
        title, company, stamp = "", "", ""
        m = TS_RE.search(folder.name)
        if m:
            stamp = m.group(1)

        if old:
            base, stamp = old_base(old)
            if base in FROM_OLD:
                company, title = FROM_OLD[base]
            elif base.startswith("company_"):
                # recover from posting
                posting = folder / "posting.md"
                if posting.is_file():
                    title, company = title_from_posting(
                        posting.read_text(encoding="utf-8", errors="replace")
                    )
                # also RESULT
                rj = folder / "RESULT.json"
                if rj.is_file():
                    try:
                        data = json.loads(rj.read_text(encoding="utf-8"))
                        rt = str(data.get("title") or data.get("short_title") or "").strip()
                        rc = str(data.get("company") or "").strip()
                        if rt and not is_bad_title(rt) and (
                            not title or is_bad_title(title) or title.lower() == "prompt engineer"
                        ):
                            # only trust RESULT title if not obviously wrong for company_* that we already fixed via posting
                            if not title or is_bad_title(title):
                                title = rt
                        if rc and (not company or company.lower().startswith("unknown")):
                            company = rc
                    except Exception:
                        pass
            else:
                # company_title from old slug
                parts = base.split("_", 1)
                if len(parts) == 2:
                    company = parts[0].replace("-", " ")
                    title = parts[1].replace("-", " ")

        # Prefer old-slug titles over polluted "Prompt Engineer" when old had a clearer role
        if old:
            base, _ = old_base(old)
            if base in FROM_OLD:
                company, title = FROM_OLD[base]

        # Remaining garbage: read posting + RESULT carefully
        if not title or is_bad_title(title) or title.lower() == "prompt engineer" and old:
            base = old_base(old)[0] if old else ""
            if base not in FROM_OLD:
                posting = folder / "posting.md"
                if posting.is_file():
                    pt, pc = title_from_posting(
                        posting.read_text(encoding="utf-8", errors="replace")
                    )
                    if pt and not is_bad_title(pt):
                        title = pt
                    if pc:
                        company = company or pc
                rj = folder / "RESULT.json"
                if rj.is_file() and (not title or is_bad_title(title)):
                    try:
                        data = json.loads(rj.read_text(encoding="utf-8"))
                        rt = str(data.get("title") or "").strip()
                        if rt and not is_bad_title(rt):
                            title = rt
                        rc = str(data.get("company") or "").strip()
                        if rc:
                            company = company or rc
                    except Exception:
                        pass

        # Special: if still bad, try old folder name parts for company_* cases
        if (not title or is_bad_title(title)) and old:
            base, _ = old_base(old)
            # strip company_ prefix fluff
            fluff = re.sub(r"^company_", "", base)
            fluff = re.sub(
                r"^(about-the-role|job-description|responsibilities|in-the-story-of-.*?)(_|$)",
                "",
                fluff,
            )
            if fluff and not fluff.startswith("https"):
                title = fluff.replace("-", " ")

        title = sanitize_job_title(title or "Target Role", max_len=40)
        company = sanitize_job_title(
            re.split(r"[(\[]", company or "", maxsplit=1)[0].strip(), max_len=24
        )
        if company.lower() in {"unknown", "n/a", "company"}:
            company = ""

        slug = folder_slug(title, company, max_len=48)
        if not stamp:
            stamp = "legacy"
        new_name = f"{slug}_{stamp}"
        n = 2
        while new_name.lower() in used and new_name.lower() != folder.name.lower():
            new_name = f"{slug}-{n}_{stamp}"
            n += 1

        if new_name == folder.name:
            print(f"KEEP {folder.name}")
            continue

        print(f"{folder.name}\n  -> {new_name}  [{company} | {title}]")
        dest = root / new_name
        folder.rename(dest)
        used.discard(folder.name.lower())
        used.add(new_name.lower())
        meta = {
            "short_title": title,
            "company": company,
            "previous_name": folder.name,
            "original_name": old,
        }
        (dest / "_folder_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        fixed.append((folder.name, new_name))

    out = root / "_rename_map_fix.json"
    out.write_text(
        json.dumps([{"from": a, "to": b} for a, b in fixed], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nFixed {len(fixed)} folders -> {out}")


if __name__ == "__main__":
    main()
