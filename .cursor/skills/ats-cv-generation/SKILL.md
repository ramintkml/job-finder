---
name: ats-cv-generation
description: >-
  Generates ATS-friendly tailored resumes from a base CV and job description using
  the Career Pilot ATS guide v2.0. Use when creating, rewriting, improving, or
  scoring resumes/CVs for LinkedIn or Telegram apply flows; when the user asks for
  a DOCX resume, ATS optimization, keyword match, or resume improve based on
  evaluation.md / ATS scores.
---

# ATS CV Generation

Follow the Career Pilot ATS guide as the source of truth for resume writing.

## Load first

1. Read `backend/app/ats/ATS_Friendly_Resume_Guide.md` (or `backend/data/ats/ATS_Friendly_Resume_Guide.md` if present).
2. Read the candidate base CV / profile evidence provided in the task.
3. Read the target job description.

For Job Search / Codex runs, the same guide is mirrored at:

`.agents/skills/job-search-copilot/references/ats-resume-guide.md`

## Pipeline (mandatory)

Execute the guide's **JD -> CV Generation Pipeline** in order:

1. Ingest base CV / evidence (only source of truth)
2. Parse JD (must-haves, nice-to-haves, deal-breakers)
3. Extract keywords (exact JD spelling)
4. Map each keyword: Claim / Bridge / Omit / Flag
5. Choose sections (drop empty optionals)
6. Write Summary (3-5 lines)
7. Write Skills (categorized; Claim keywords first)
8. Rewrite Experience bullets (verb + tech + result; facts fixed)
9. Add Projects only if they improve truthful fit
10. Education / Certs compact and accurate
11. Run **Pre-Output Self-Check**
12. Prefer **DOCX** single-column export
13. Score with the 100-point rubric; if <80 and truthful gains remain, revise weak categories only

## Hard rules

- Never invent employers, titles, dates, degrees, metrics, or tools
- Single-column only — no tables, columns, graphics, headers/footers
- Approved action verbs from the guide only at bullet starts
- Keyword density ~1-3 natural mentions; no stuffing
- On Improve: raise or maintain ATS score using evaluation.md + ATS tips without fabrication

## Outputs

Depending on the caller:

- Structured resume JSON (VPS Groq tailor path), or
- `resume.md` + DOCX (Codex / job-search-copilot path)

DOCX must follow the **Ramin Takmil CV template**: Calibri, single-column, ruled section headings, section order
Header → Professional Summary → Core Skills → Selected Projects → Additional Experience →
Professional Experience → Research → Education → Languages & Certifications.

Always keep claims evidence-backed.
