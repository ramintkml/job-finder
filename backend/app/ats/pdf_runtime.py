"""Offline native-runtime check: real base-CV DOCX/PDF, no users, DB or AI."""
from __future__ import annotations

from importlib import import_module
import json
from pathlib import Path
import tempfile
from zipfile import ZipFile


SAMPLE = """PDF Runtime Check
Software Engineer
check@example.invalid | Remote
PROFESSIONAL SUMMARY
Builds reliable Python applications.
CORE SKILLS
Backend: Python, SQL
SELECTED PROJECTS
- Runtime Verification
  - Verified offline document export without user data.
EDUCATION
BSc Computer Science
"""


def check_pdf_runtime() -> dict:
    try:
        numpy = import_module("numpy")
        if int(numpy.dot([1, 2], [3, 4])) != 11:
            raise RuntimeError("Numeric runtime returned an invalid result")
    except Exception as exc:
        raise RuntimeError(
            "PDF native runtime unavailable: NumPy cannot initialize on this CPU. "
            "Install the pinned requirements before starting the service."
        ) from exc

    from app.ats.base_cv_export import export_base_cv_files

    with tempfile.TemporaryDirectory(prefix="career-pilot-pdf-check-") as directory:
        docx, pdf = export_base_cv_files(SAMPLE, Path(directory), allow_partial=False)
        if pdf is None:
            raise RuntimeError("Base CV export did not produce its required PDF")
        data = pdf.read_bytes()
        if not data.startswith(b"%PDF-") or not data.rstrip().endswith(b"%%EOF") or len(data) < 1000:
            raise RuntimeError("Base CV PDF output is incomplete or invalid")
        with ZipFile(docx) as archive:
            document = archive.read("word/document.xml").decode("utf-8")
        if "Runtime Verification" not in document:
            raise RuntimeError("Base CV DOCX output lost the test project")
        return {"status": "PDF_RUNTIME_OK", "numpy": numpy.__version__,
                "pdf_bytes": len(data), "docx_bytes": docx.stat().st_size,
                "user_data_used": False, "network_used": False}


if __name__ == "__main__":
    print(json.dumps(check_pdf_runtime(), ensure_ascii=True))
