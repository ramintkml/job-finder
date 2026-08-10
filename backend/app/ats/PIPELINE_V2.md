# ATS Resume Pipeline v2 — Design Spec

Status: **design only** (not wired into production yet)  
Goal: stop one-shot CV writing; make keywords a locked ledger that code enforces before export.

---

## 1. Principles

1. **Ledger first, prose second** — nothing Claimable is “optional flavor.”
2. **Exact JD spelling is the scored form** — aliases only help evidence matching.
3. **Code owns insertion + verification** — LLM may classify and phrase; it does not get a free pass to drop Claim terms.
4. **Improve = gap fill against the ledger** — not a full rewrite.
5. **Truthfulness unchanged** — Omit never enters Skills/bullets.

---

## 2. File layout (proposed)

```
backend/app/ats/
  PIPELINE_V2.md              ← this spec
  pipeline_v2/
    __init__.py
    schema.py                 ← TypedDict / pydantic models + JSON schema helpers
    extract.py                ← hybrid JD keyword extraction (wrap/replace keywords.py)
    evidence_match.py         ← alias expand + find evidence snippets in base CV
    classify.py               ← AI (or rules) → Claim/Bridge/Omit/Flag per keyword
    ledger.py                 ← build + validate KeywordLedger
    slots.py                  ← empty resume slot template from base CV structure
    write_slots.py            ← AI fills Summary / bullets / project blurbs only
    hard_insert.py            ← Stage C: force Claim terms into Skills (+ optional bullet tags)
    self_check.py             ← ledger + rubric gates
    assemble.py               ← merge slots → structured resume dict
    run.py                    ← orchestrator: JD + base_cv → resume dict + ledger + score
  score.py                    ← keep; score against ledger.jd_terms (exact)
  docx_export.py              ← unchanged exporter
  tailor.py                   ← later: thin wrapper calling pipeline_v2.run
```

Codex / Job Search side (later mirror):

```
Job Search/.agents/skills/job-search-copilot/
  references/
    ats-resume-guide.md       ← keep truthfulness rules
    keyword-ledger.schema.json
  scripts/                    ← optional: local ledger builder if agent path stays
```

Artifact layout per application (PC + VPS):

```
applications/<slug>_<ts>/
  posting.md
  keyword_ledger.json         ← NEW source of truth
  resume.md / resume structured
  evaluation.md
  RESULT.json                 ← includes ledger path + score breakdown
```

---

## 3. Keyword ledger schema

### 3.1 Top-level JSON

```json
{
  "version": "2.0",
  "job": {
    "title": "Machine Learning Engineer",
    "company": "Example Co",
    "url": "https://..."
  },
  "generated_at": "2026-08-10T07:00:00Z",
  "source": {
    "base_cv_chars": 12000,
    "jd_chars": 4500,
    "extractor": "hybrid_v2"
  },
  "terms": [ /* KeywordTerm[] */ ],
  "summary": {
    "claim_count": 18,
    "bridge_count": 4,
    "omit_count": 9,
    "flag_count": 1,
    "must_have_claimable": 12,
    "must_have_missing": 3
  },
  "placement_plan": {
    "skills_must_include": ["machine learning", "Python", "Docker"],
    "summary_prefer": ["machine learning", "PyTorch", "FastAPI"],
    "bullet_tags": [
      {"term": "machine learning", "target": "experience:AI Specialist", "hint": "medical imaging models"},
      {"term": "Docker", "target": "project:Medinex", "hint": "containerized Flask services"}
    ]
  }
}
```

### 3.2 `KeywordTerm` object

```json
{
  "id": "kw_machine_learning",
  "jd_term": "machine learning",
  "priority": "must_have",
  "aliases": ["ML", "machine-learning", "deep learning", "Deep Learning"],
  "decision": "Claim",
  "confidence": 0.92,
  "evidence": {
    "source": "base_cv",
    "snippet": "Strong in Python, LLM integration, computer vision...",
    "match_via": "alias:deep learning|computer vision context",
    "char_start": 420,
    "char_end": 510
  },
  "bridge_phrase": null,
  "omit_reason": null,
  "placements": {
    "skills": true,
    "summary": true,
    "bullets_min": 1,
    "bullets_max": 2
  },
  "surface_forms": {
    "write_as": "machine learning",
    "skills_as": "machine learning",
    "allowed_extra": ["ML"]
  },
  "status": {
    "in_draft_skills": false,
    "in_draft_summary": false,
    "in_draft_bullets": 0,
    "hard_insert_applied": false
  }
}
```

### 3.3 Field rules

| Field | Rule |
|-------|------|
| `jd_term` | Exact spelling from JD (scoring key). Lowercase normalize only for compare; store original JD casing when possible. |
| `aliases` | Used only to find evidence in base CV / profile. Never scored unless also written. |
| `decision` | `Claim` \| `Bridge` \| `Omit` \| `Flag` |
| `priority` | `must_have` \| `nice_to_have` \| `inferred` |
| `evidence.snippet` | Required for Claim/Bridge. Empty → cannot Claim. |
| `bridge_phrase` | Required if Bridge; honest adjacent wording approved for writer. |
| `write_as` | What Stage C inserts. Defaults to `jd_term`. |
| `placements.skills` | Claim must-haves default `true`. |
| `bullets_min` | Stage C tries to reach this after writer; 0 = skills-only OK. |

### 3.4 Decision algorithm (classify)

For each extracted JD term:

```
evidence_hit = fuzzy/alias search in base_cv + evidence.md + candidate.md

if exact or alias hit with clear support:
    decision = Claim
elif close adjacent skill exists (e.g. ChromaDB for "vector DB"):
    decision = Bridge + bridge_phrase
elif eligibility/location/visa style constraint:
    decision = Flag
else:
    decision = Omit
```

Hard bans (always Omit unless explicitly evidenced by name):
- Named CI vendors not in evidence (GitHub Actions, Jenkins, …) unless ledger later marks Claim
- Cloud/K8s products not evidenced
- Years of experience claims not in base CV

### 3.5 Alias pack (seed — extend over time)

```yaml
machine learning: [ML, machine-learning, deep learning, DL]
continuous integration / continuous delivery: [CI/CD, CI CD, cicd]
version control: [Git, GitHub, versioning]
REST API: [RESTful, RESTful API, REST APIs]
large language models: [LLM, LLMs, GenAI]
computer vision: [CV, image processing]
```

Aliases are **evidence helpers**. Writer still emits `jd_term` (e.g. write `"machine learning"` even if evidence said `"deep learning"`), when Claim is valid.

---

## 4. Stage pipeline (runtime)

```
base_cv + JD
    │
    ▼
[1 extract]     hybrid keywords → candidate jd_term list
    │
    ▼
[2 evidence]    alias expand → snippets
    │
    ▼
[3 classify]    Claim/Bridge/Omit/Flag (+ optional AI adjudicator)
    │
    ▼
[4 ledger]      keyword_ledger.json  ← FREEZE
    │
    ▼
[5 slots]       copy facts from base CV (titles, dates, employers fixed)
    │
    ▼
[6 write]       AI fills Summary + bullet phrasing ONLY
                Input: ledger (Claim/Bridge only) + frozen facts
    │
    ▼
[7 hard_insert] Stage C — code forces missing Claim surfaces
    │
    ▼
[8 self_check]  fail if Claim missing or Omit present
    │
    ▼
[9 score]       existing rubric; keyword list = ledger Claim+Bridge write_as terms
                (optionally score must_have Claim subset harder)
    │
    ▼
[10 export]     DOCX / PDF / FA translate (unchanged exporters)
```

---

## 5. Stage C — Hard insert algorithm

**File:** `pipeline_v2/hard_insert.py`  
**Input:** structured `resume: dict`, `ledger: KeywordLedger`  
**Output:** mutated resume + updated `term.status` + `insert_log[]`

### 5.1 Pseudocode

```text
function hard_insert(resume, ledger):
    text = flatten_resume_text(resume).lower()
    insert_log = []

    claim_terms = [t for t in ledger.terms if t.decision in ("Claim", "Bridge")]
    # Bridge uses bridge_phrase for bullets; write_as (jd spelling) still forced into Skills when placements.skills

    # --- Pass 1: Skills ---
    skills = ensure_skills_dict(resume)   # categorized dict
    catchall = skills.setdefault("JD Keywords", [])  # or merge into existing best category

    for t in claim_terms:
        surface = t.surface_forms.write_as
        if not t.placements.skills:
            continue
        if not contains_term(text, surface) and not contains_any(text, t.aliases):
            # Prefer JD spelling in Skills even if alias was in prose
            add_unique(catchall, surface)
            t.status.in_draft_skills = True
            t.status.hard_insert_applied = True
            insert_log.append({op: "skills_add", term: surface})
        elif contains_term(flatten_skills(skills), surface) or contains_any(flatten_skills(skills), t.aliases):
            # Normalize alias-only skills entry → also ensure jd_term present
            if not contains_term(flatten_skills(skills), surface):
                add_unique(catchall, surface)
                insert_log.append({op: "skills_normalize", term: surface})
            t.status.in_draft_skills = True

    refresh text

    # --- Pass 2: Summary (light) ---
    for t in claim_terms:
        if not t.placements.summary:
            continue
        surface = t.surface_forms.write_as
        if contains_term(resume.summary, surface):
            t.status.in_draft_summary = True
            continue
        if t.priority != "must_have":
            continue
        if t.decision == "Omit":
            continue
        # Append a short clause only if summary has room (< ~5 lines / ~600 chars)
        if len(resume.summary) < 550 and not contains_term(resume.summary, surface):
            resume.summary = append_clause(resume.summary, surface, t.evidence.snippet)
            t.status.in_draft_summary = True
            t.status.hard_insert_applied = True
            insert_log.append({op: "summary_clause", term: surface})

    refresh text

    # --- Pass 3: Bullets (tag, don't fabricate) ---
    for t in claim_terms:
        need = t.placements.bullets_min or 0
        have = count_term_in_bullets(resume, t)
        t.status.in_draft_bullets = have
        if have >= need:
            continue
        target = find_placement_target(resume, ledger.placement_plan, t)
        if target is None:
            insert_log.append({op: "bullet_skip_no_target", term: t.jd_term})
            continue
        # Inject JD term into an existing bullet that already discusses related work
        # NEVER create a new employer or metric
        phrase = surface_for_bullet(t)  # Claim: write_as; Bridge: may use bridge_phrase + write_as once
        new_bullet = weave_term_into_bullet(target.bullet_text, phrase)
        if new_bullet != target.bullet_text and word_count(new_bullet) <= 28:
            target.bullet_text = new_bullet
            t.status.in_draft_bullets += 1
            t.status.hard_insert_applied = True
            insert_log.append({op: "bullet_weave", term: phrase, target: target.id})
        else:
            insert_log.append({op: "bullet_skip_too_long", term: t.jd_term})

    # --- Pass 4: Verify ---
    text = flatten_resume_text(resume).lower()
    missing_claim = []
    for t in claim_terms:
        if t.decision != "Claim":
            continue
        if t.priority == "must_have" and not contains_term(text, t.surface_forms.write_as):
            missing_claim.append(t.jd_term)

    return resume, insert_log, missing_claim
```

### 5.2 `contains_term` rules

```text
function contains_term(haystack, term):
    h = normalize(haystack)          # lower, collapse whitespace
    t = normalize(term)
    # word-boundary-ish match to avoid "AI" matching inside "email"
    return regex_search(r"(?<![a-z0-9])" + escape(t) + r"(?![a-z0-9])", h)
```

Aliases are **not** enough to pass Stage C verification for Claim must-haves — the `write_as` / `jd_term` must appear.

### 5.3 What Stage C must never do

- Add Omit terms
- Invent metrics, employers, dates, degrees
- Create new project/experience entries
- Exceed ~1–3 natural mentions by blasting the same term everywhere (Skills once + Summary optional + ≤ bullets_max)

### 5.4 Failure behavior

If `missing_claim` non-empty after Stage C:

1. Retry Pass 1 with a dedicated `"Core Skills"` / `"JD Keywords"` category (already done)
2. If still missing → **fail self_check** and either:
   - re-queue write_slots with `forced_terms=[...]`, or
   - return resume + warning `ats_notes: "Claim terms could not be placed: ..."` and lower confidence

Do not silently ship a draft that omits Claim must-haves.

---

## 6. Self-check gates (before export)

```text
PASS only if:
  [ ] no Omit term appears in Skills or bullets (exact)
  [ ] every Claim + must_have has write_as in flatten text
  [ ] every experience bullet starts with approved verb
  [ ] ≥ 50% bullets have metric/outcome (existing heuristic)
  [ ] summary length 3–5 lines
  [ ] no fabricated fields vs base CV fact freeze
```

---

## 7. Scoring integration

Keep `score.py` categories.

Change keyword input:

```text
scored_keywords = [
  t.surface_forms.write_as
  for t in ledger.terms
  if t.decision in ("Claim", "Bridge")
]
# Optional second pass:
# must_have_only = Claim ∩ must_have  → report separately in ats_scoring.hybrid_keywords
```

Do **not** score Omit terms (that inflates “missing” unfairly).  
Today’s pain (“machine learning missing”) is Claimable-but-unwritten; ledger + Stage C fixes that.

Target operating band after v2:
- Keyword category: aim ≥ 16/20 when ≥80% of JD must-haves are Claimable
- Total: aim 80–88 truthful; 90+ only when Claim coverage is rich

---

## 8. Improve flow (v2)

```text
Load previous resume + same or refreshed ledger
missing = Claim must_haves not in resume text
hard_insert(resume, ledger restricted to missing)
if still gaps: write_slots only for affected bullets/summary
re-score; refuse full creative rewrite
```

Telegram Improve button should attach `keyword_ledger.json` (or rebuild from JD + base CV).

---

## 9. Example — “machine learning”

JD term: `machine learning`  
Base CV: “Deep learning, LLMs… computer vision…”

```json
{
  "jd_term": "machine learning",
  "aliases": ["ML", "deep learning"],
  "decision": "Claim",
  "evidence": {"snippet": "Deep learning, LLMs & prompt engineering, computer vision...", "match_via": "alias:deep learning"},
  "surface_forms": {"write_as": "machine learning"},
  "placements": {"skills": true, "summary": true, "bullets_min": 1}
}
```

Writer might say “deep learning models…”.  
Stage C then:
1. Adds `machine learning` to Skills  
2. Weaves `machine learning` into one AI Specialist / Dentistry bullet if still absent from body  
3. Self-check passes only when substring `machine learning` exists

---

## 10. Implementation order (when you approve code)

1. `schema.py` + `ledger.py` + sample `keyword_ledger.json` fixture  
2. `evidence_match.py` + alias pack + unit tests (“ML” evidence → Claim `machine learning`)  
3. `hard_insert.py` + tests on a frozen resume dict  
4. `run.py` orchestrator behind a feature flag  
5. Point `tailor.py` / Codex prompt at ledger artifacts  
6. Wire Improve to ledger gap fill  
7. Retire one-shot “write whole CV” prompts

---

## 11. Locked decisions

1. **Skills placement for hard-insert:** merge into **existing categories** via keyword→category map; only if no map hit, append to the largest/most relevant existing category (never a separate "JD Keywords" section).
2. **Score Omit terms?** **No** — scored keyword list = Claim + Bridge `write_as` only.
3. **Rollout order:** **VPS tailor path first** (`tailor.py` → `pipeline_v2.run`); Codex/Job Search mirror later.
4. **Bridge in Skills:** **Yes** — Bridge terms also get `write_as` (JD spelling) in Skills; bullets may still use `bridge_phrase` for honesty.

---

## 12. Success criteria

- Re-run Snappfood (or similar) JD: Claimable terms like `machine learning` appear in Skills with exact spelling  
- ATS keyword subscore rises when Claim coverage exists; total moves out of permanent 70–75 plateau when metrics/verbs already OK  
- Improve no longer drops previously Claimed terms  
- Zero Chinese/CJK issues unrelated; FA translate stays a post-step on frozen EN resume
