"""User-owned CV storage with revision history and conflict-safe edits."""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from contextlib import contextmanager

from app.config import DATA_DIR

CV_ROOT = DATA_DIR / "user_cvs"


def cv_path(user_id: int) -> Path:
    if int(user_id) <= 0:
        raise ValueError("Invalid Telegram user id")
    return CV_ROOT / str(int(user_id)) / "base_cv.txt"


def read_cv(user_id: int) -> str:
    path = cv_path(user_id)
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


@contextmanager
def _exclusive_lock(path: Path):
    # OS locks release automatically on process exit, including a server crash.
    with path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise FileExistsError("Another CV update is in progress") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def write_cv(user_id: int, text: str, *, expected: str | None = None) -> Path:
    text = text.strip()
    if len(text) < 40 or len(text) > 200000:
        raise ValueError("CV must contain 40 to 200000 characters")
    path = cv_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Serializes writers across server processes.
    lock = path.with_suffix(".lock")
    with _exclusive_lock(lock):
        previous = read_cv(user_id)
        if expected is not None and fingerprint(previous) != expected:
            raise ValueError("CV changed; please start the update again")
        if previous:
            history = path.parent / "history"
            history.mkdir(exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            (history / f"{stamp}_{uuid4().hex}.txt").write_text(previous, encoding="utf-8")
        temp = path.with_name(f".{uuid4().hex}.tmp")
        try:
            temp.write_text(text, encoding="utf-8")
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
    return path


def append_entry(base: str, entry: str, *, section: str = "projects") -> str:
    """Preserve the user's facts verbatim and insert into the requested section."""
    entry = entry.strip()
    if not 10 <= len(entry) <= 12000:
        raise ValueError("Entry must contain 10 to 12000 characters")
    headings = {
        "projects": ("SELECTED PROJECTS", r"selected projects|projects|پروژه‌های منتخب|پروژه‌ها"),
        "experience": ("PROFESSIONAL EXPERIENCE", r"professional experience|work experience|سوابق شغلی"),
        "skills": ("CORE SKILLS", r"core skills|skills|مهارت‌ها"),
    }
    heading, pattern = headings[section]
    lines = entry.splitlines()
    block = "- " + lines[0].lstrip("-*• ")
    block += "".join("\n  - " + line.lstrip("-*• ") for line in lines[1:] if line.strip())
    match = re.search(r"(?im)^\s*#{0,3}\s*(?:" + pattern + r")\s*$", base)
    if match:
        return base[:match.end()] + "\n\n" + block + "\n" + base[match.end():]
    return base.rstrip() + "\n\n" + heading + "\n\n" + block + "\n"
