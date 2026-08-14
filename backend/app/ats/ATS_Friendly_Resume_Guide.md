# ATS-Friendly Resume Guide for AI Systems

Version: 2.0

Language: English (see Persian Addendum for Farsi-market rules)

Purpose: Explicit, operational rules for generating Applicant Tracking System (ATS) friendly resumes. Written so humans and LLMs can apply the same pipeline consistently — especially for tailored CV generation from a base CV + job description.

## Version History

- **1.0** — Sections, bullet formula, action verbs, basic ATS formatting.
- **1.1** — Fonts/file-naming, DOCX vs PDF, date consistency, header/footer ban, PII, freelance section, keyword density, proofreading.
- **1.2** — Readability/Grammar scoring methods, Persian addendum.
- **2.0** — Hard constraints, JD→CV pipeline, truthfulness protocol, scorer-aligned verbs & rubrics, section order rules, tech/AI stacking, bad→good rewrites, pre-output self-check. Skill-ready for automated CV generation.

---

## Objective

Generate resumes that:

1. Pass ATS parsers (text extractable, standard structure)
2. Are easy for recruiters to skim in ~6 seconds
3. Match the target job description with **truthful** keyword overlap
4. Maximize interview odds without fabricating experience
5. Score well on the 100-point rubric in this guide

---

## Hard Constraints (non-negotiable)

| Rule | Requirement |
|------|-------------|
| Layout | **Single column only** — no tables, text boxes, columns, sidebars |
| Headers/footers | **Never** put name, contact, or content in Word headers/footers |
| Graphics | No icons, images, logos, charts, skill bars, watermarks |
| Colors | Black text on white background |
| Fonts | Calibri, Arial, or Georgia — body **10.5–12pt**, name **14–16pt** |
| Margins | 0.5"–1" all sides |
| Alignment | Left-aligned throughout |
| Length | **1 page** if &lt;8 years experience; **2 pages max** otherwise |
| File format | **DOCX by default**; PDF only if the posting requires/allows it |
| File name | `FirstName_LastName_Role_Resume.docx` (no "Final_v3") |
| Dates | One format for the whole doc: `MMM YYYY` or `MM/YYYY` — never mix |
| Bullets | Standard round/square bullets only; **3–6 bullets per role** |
| Bullet length | Ideally **≤25 words**; one action → one result |
| Summary | **3–5 lines** (≈50–90 words), not a paragraph essay |
| Contact PII (EN/intl) | No photo, DOB, marital status, national ID |
| Fabrication | **Never** invent employers, titles, dates, degrees, metrics, or skills |

Heading whitelist (use these exact labels when possible):

`Summary` · `Professional Experience` · `Skills` · `Projects` · `Education` · `Certifications`

Allowed variants: `Professional Summary`, `Work Experience`, `Technical Skills`, `Selected Projects`. Do not invent creative headings (`My Journey`, `What I Bring`).

---

## Recommended Section Order

Default Career Pilot / Ramin Takmil template (match DOCX export):

1. **Header** (name, title, contact — in body, not Word header)
2. **Professional Summary**
3. **Core Skills** (early = better ATS keyword capture)
4. **Selected Projects**
5. **Additional Experience** (optional compact themes)
6. **Professional Experience**
7. **Research** (optional)
8. **Education**
9. **Languages & Certifications**

For traditional corporate roles where projects are secondary, you may place Professional Experience above Selected Projects — keep all other styling identical.

Drop empty optional sections rather than writing "N/A".

---

## Fundamental Principles

### Content over design

ATS systems analyze extracted text. A beautiful multi-column resume that fails parsing scores zero.

### Truthfulness over keyword stuffing

Exact JD wording helps **only** when the candidate actually has that skill/experience. Prefer omit or honest adjacent phrasing over fake claims.

### One idea per bullet

Each bullet = one verb + one tech/context + one result (when available).

---

## Resume Header

Include in the document body:

- Full Name
- Professional Title (aligned to target role when truthful)
- Email · Phone · Location (city/country or Remote)
- LinkedIn · GitHub · Portfolio (omit if not available)

Do **not** include (English / international ATS): photo, DOB, marital status, national ID.

---

## Professional Summary

3–5 lines covering:

1. Years / seniority + role identity
2. Specialization (domain + stack)
3. 2–4 core technologies matching the JD (truthful only)
4. One concrete business/impact signal if available

**Good:**
> AI/ML engineer with 4+ years building production LLM and computer-vision systems. Strong in Python, PyTorch, RAG pipelines, and FastAPI services. Shipped models that cut manual review time by 30%+ for client workflows.

**Bad:**
> Hard-working team player passionate about AI seeking new opportunities to grow…

---

## Skills

- Group by category (e.g. Languages, ML/AI, Backend, Cloud/DevOps, Tools)
- Prefer **exact JD spellings** when truthful (`PyTorch` not just `deep learning`)
- 1–3 natural mentions of each core keyword across Summary + Skills + bullets — more looks like stuffing
- No skill bars, ratings, or icon grids

---

## Experience

Each role:

- Job Title
- Company (or "Self-Employed / Freelance")
- Dates (`MMM YYYY – MMM YYYY` or `Present`)
- 3–6 achievement bullets

### Bullet formula

```text
Action Verb + What you built/did + Technology/context + Measurable result (if available)
```

### Approved action verbs (scorer-aligned)

Developed, Designed, Built, Implemented, Optimized, Automated, Deployed, Integrated, Led, Improved, Created, Delivered, Engineered, Architected, Reduced, Increased, Launched, Migrated, Refactored, Scaled.

**Avoid starting bullets with:** Worked on, Helped, Responsible for, Involved in, Participated in, Assisted with.

### Quantify when truthful

Use metrics from the base CV / evidence only: %, latency, accuracy, users, $ impact, time saved, scale (QPS, docs, models). If no metric exists, prefer a clear outcome over inventing a number.

### Freelance / contract work

When engagements are parallel rather than sequential:

- One umbrella entry: title + Self-Employed + overall date range
- 3–6 representative project bullets (Action Verb + Tech + Result)
- Group similar work if the list is long
- Omit client names under NDA; describe problem + outcome

---

## Projects

Always include **all five** Selected Projects from the base CV. Never drop one.

- Reorder by JD relevance (closest stack/domain first; others still listed)
- Parent bullet: project name + GitHub and/or live URL
- Sub-bullets: 3–6 truthful facts, rewritten with Claim/Bridge JD spellings
- Required links: Bendly (github.com/Bendly-app | https://stg.bendly.io/), Medinex (github.com/ramintkml/medinex | medinex.top), OT Clinic (github.com/ramintkml/ot-clinic | fereshteganrehab.ir), Job Finder (github.com/ramintkml/job-finder), Roof Graph Extraction (github.com/ramintkml/Roof_Graph_Extraction)

```text
- Project Name — github.com/... | live-url
  - Developed ... (JD-aligned, evidence-backed)
  - Implemented ...
```

Do not invent extra projects. Extra Experience themes stay under Additional Experience.

---

## Education & Certifications

- Degree, school, dates (and honors only if real)
- Certifications as a short list — no logos

---

## Keywords

1. Extract required skills/tools from the JD (must-haves first)
2. Intersect with base CV / evidence
3. Use **exact terminology** from the JD for the intersection
4. Density: each core keyword ~1–3 times across the resume
5. Never: white text, hidden layers, or keywords in unrelated sections

---

## Truthfulness Protocol

For every JD requirement, choose **exactly one**:

| Decision | When | What to write |
|----------|------|----------------|
| **Claim** | Explicitly supported by base CV / evidence | Use JD wording where natural |
| **Bridge** | Closely related experience exists | Honest adjacent phrasing (“built retrieval pipelines with ChromaDB” — not “5 years Azure AI Foundry”) |
| **Omit** | Not supported | Do not list it in Skills or bullets |
| **Unknown / flag** | Deal-breaker for apply advice (visa, onsite, clearance) | Flag in evaluation/advice — never fake eligibility |

**Never invent:** employers, titles, dates, degrees, certifications, metrics, tools, or domain experience.

If improving a prior draft: only raise ATS score with truthful rewrites (reorder, rephrase, emphasize) — not fabrication.

---

## Tech / AI Role Stacking

For ML / LLM / Agentic / Data roles:

1. Lead with the JD’s primary stack (e.g. LLM, RAG, Python) if truthful
2. Put supporting tools in Skills categories matching the posting
3. Prefer production/shipping language when true (`Deployed`, `Scaled`, `Automated`)
4. Do **not** claim frameworks only mentioned in the JD (CrewAI, LangGraph, SHAP, etc.) unless evidenced
5. Thesis / coursework may **bridge** research topics — never upgrade them into production claims

---

## ATS Formatting Checklist

Use:

- Black text, white background
- DOCX (default) or PDF per posting
- Left alignment, standard bullets
- Body flow only (no header/footer content)

Avoid:

- Columns, tables, text boxes
- Graphics, charts, icons, watermarks
- Text in headers/footers

---

## JD -> CV Generation Pipeline (for AI / skills)

Execute in order. Do not skip.

1. **Ingest** base CV / profile / evidence (source of truth).
2. **Parse JD** — title, must-haves, nice-to-haves, location/eligibility constraints.
3. **Extract keywords** — required skills/tools/phrases (preserve exact spelling).
4. **Map evidence** — for each keyword: Claim / Bridge / Omit / Flag.
5. **Choose section set** — drop empty optionals.
6. **Write Summary** — 3–5 lines; JD-aligned title/stack; truthful only.
7. **Write Skills** — categorized; Claim keywords first.
8. **Rewrite Experience bullets** — verb + tech + result; tailor emphasis to JD; keep facts fixed.
9. **Write Selected Projects** — include all five base-CV projects; reorder by JD; parent bullet + sub-bullets; keep GitHub/live links; tailor details with Claim/Bridge spellings only.
10. **Education / Certs** — compact, accurate.
11. **Self-check** (below) — fix failures before export.
12. **Export DOCX** — single-column, Calibri/Arial, no tables/headers/footers.
13. **Score** with the rubric — if &lt;80 and truthful gains remain, revise weak categories only.

If the JD is vague: infer likely keywords from role/industry, mark them as inferred, and avoid over-claiming.

---

## Pre-Output Self-Check

Fail the draft if any box is unchecked:

- [ ] No fabricated employers, dates, degrees, metrics, or tools
- [ ] Every Claim keyword appears in Skills and/or bullets where natural
- [ ] Omit list is respected (no sneaky JD-only tools)
- [ ] Every experience bullet starts with an approved action verb
- [ ] ≥ ~50% of bullets include a truthful metric or clear outcome
- [ ] No bullet &gt; ~25 words; no multi-idea “and…and…” bullets
- [ ] Dates use one consistent format
- [ ] Single-column; no tables/graphics/headers/footers
- [ ] Summary is 3–5 lines
- [ ] Tense consistent (past roles past tense; current role present)
- [ ] Bullet end-punctuation consistent (all periods or none)
- [ ] File would be named `FirstName_LastName_Role_Resume.docx`

---

## Bad -> Good Rewrites

**Weak**
- Worked on AI models for the company.

**Strong**
- Built PyTorch classification models that improved precision by 12% on production traffic.

---

**Weak**
- Responsible for RAG and chatbots using various tools.

**Strong**
- Implemented a ChromaDB RAG pipeline in Python that cut support lookup time by ~40% for internal users.

---

**Weak**
- Helped with cloud deployment and Azure AI Foundry agents. *(when Azure isn’t evidenced)*

**Strong (Omit + Bridge)**
- Deployed LLM workflows with FastAPI and Docker; automated evaluation scripts for prompt/quality checks.

---

## ATS Scoring Rubric (100 points)

Aligned with Career Pilot / Freelancer automation scoring:

| Category | Max | How to earn |
|----------|-----|-------------|
| Formatting | 20 | Single-column DOCX/PDF path; no tables/columns/graphics/headers-footers |
| Keyword match | 20 | Share of JD keywords present in resume text (truthful intersection) |
| Achievements | 15 | Share of bullets containing a measurable result |
| Action verbs | 10 | Share of bullets starting with an approved verb |
| Readability | 10 | See method below |
| Skills | 10 | Skills section present and grouped by category |
| Projects | 10 | Relevant projects/freelance work clearly listed |
| Grammar | 5 | See method below |

**Bands:** 90–100 Excellent · 80–89 Good · 70–79 Fair · &lt;70 Needs Improvement

**Target for generation:** aim ≥80. On regenerate/improve, raise or maintain total without inventing facts.

### Readability scoring method

Start at 10, deduct:

- **-2** any bullet &gt;25 words
- **-2** any bullet with more than one distinct idea
- **-2** inconsistent bullet starts (some verbs, some nouns)
- **-2** prose blocks under Experience/Projects (must be bullets)
- **-2** heavy unexplained jargon on first use  
Floor: 0.

### Grammar scoring method

Start at 5, deduct:

- **-1** per spelling error (max -3)
- **-1** inconsistent verb tense within/across similar entries
- **-1** inconsistent bullet-end punctuation
- **-1** subject-verb agreement errors
- **-1** inconsistent capitalization of headings/titles  
Floor: 0.

---

## AI Operating Rules (summary)

1. Base CV / evidence is the only source of truth.
2. Parse JD → map keywords → Claim / Bridge / Omit / Flag.
3. Tailor wording and emphasis; never invent facts.
4. Strong verbs + metrics when available.
5. Keyword optimize without stuffing.
6. Prefer DOCX single-column export.
7. Run self-check, then score; revise weak categories only.
8. For apply-advice flows: surface deal-breakers and Skip/Conditional/Apply from CV vs JD honestly.

---

## Persian (Farsi) Resume Addendum

Persian-market and English/international-ATS resumes follow **different conventions**. Pick the audience first; do not mix rules in one file.

### When to use

- Local Iranian employer, Persian posting, or explicit request for a Farsi رزومه
- International/remote/Western ATS → use English rules above (translate content; don’t apply Persian PII conventions)

### Layout & typography

- Full **RTL** layout
- Persian-capable fonts (Vazir, IRANSans, Yekan); embed fonts in PDF when needed
- Persian digits for fully local audience; Latin digits if bilingual/international parsing is possible

### Dates

- Jalali for local audience (e.g. ۱۴۰۲/۰۳ or خرداد ۱۴۰۲)
- Add Gregorian in parentheses or ship a separate Gregorian file if international readers/ATS may see it

### PII (reversed vs English)

Local Persian resumes may include: photo, DOB, marital status, military service status.  
**Omit these** for international/ATS pipelines — keep two files.

### Structure & wording

- Persian section headers for local docs
- Match the posting’s own Persian/technical terminology
- Prefer concise, complete Persian bullets — not literal English calques

### Technical caution

Some local ATS engines poorly parse RTL PDFs — prefer **DOCX** and verify copy-paste extraction before submit.

---

## Golden Rule

An ATS-friendly resume is **simple**, **truthful**, **keyword-aligned**, **results-oriented**, and **tailored to one job** — never fabricated to chase a score.
