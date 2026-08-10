# LinkedIn Job Finder — Agent Brief

Use this file as the starting context for a new Cursor agent. Open this folder as the workspace.

**Product name:** LinkedIn Job Finder  
**Source fork of:** `C:\Users\Ramin\Development\Freelancer automation` (Job Tracker)  
**Created:** 2026-07-21  
**Status:** Code copied from source; **not yet stripped or multi-user**. This brief defines the target product.

---

## What to build

A **Telegram-bot-first** app that finds LinkedIn jobs for **many users**.

| Keep | Drop |
|------|------|
| LinkedIn guest search → CV match → notify | Freelancer.com OAuth / poll / bid |
| Per-user personalized settings (today’s LinkedIn + relevant app settings) | Telethon bid automation (`@KayaProjectsBot`) |
| Telegram review actions (Create email / Create resume / Skip) | Freelancer dashboard tabs & bid pricing |
| Optional ATS resume tailor + Gmail apply email | Single global `TELEGRAM_REVIEW_CHAT_ID` gate |
| RAG CV scoring | Proposal guide / Freelancer filters as product surface |

**Primary UX:** users start and configure everything in Telegram. Web dashboard is optional (admin or later).

---

## Product vision (target)

1. User opens the Telegram bot → `/start`
2. Bot registers them as a `User` (telegram id + chat id)
3. User configures **their** settings in bot menus (search phrases, location, thresholds, CV, Gmail, profile, AI prefs, test mode, etc.)
4. Background poller runs **per user** (respecting each user’s `enabled` + `poll_interval_minutes`)
5. Matched jobs are sent **to that user’s chat** with buttons
6. User actions (email / resume / skip) apply only to their jobs

---

## Current source reality (important)

The copied codebase is still the **single-operator Job Tracker**:

- One SQLite DB, one `app_settings` key-value store
- One global `linkedin_settings` JSON blob
- Review bot allows **one** `TELEGRAM_REVIEW_CHAT_ID`
- `LinkedInJob` / `AtsResume` have **no `user_id`**
- Freelancer + Telethon code is still present under `backend/app/freelancer/` and large parts of `telegram/service.py`

Your job is to **turn this into a multi-user LinkedIn-only product**, not to keep operating it as Job Tracker.

---

## Suggested implementation order

### Phase 0 — Rename & strip (do first)

1. Rename product strings / README to **LinkedIn Job Finder**
2. Remove or stop loading:
   - `backend/app/freelancer/`
   - Freelancer API routes, poll loops, bid worker jobs
   - Telethon user-client bidding paths
   - Frontend Freelancer tabs (or delete frontend until needed)
3. Slim `backend/app/main.py` lifespan to: DB init → Review bot → LinkedIn poller (+ optional ATS/worker/alerts)
4. Slim `backend/.env.example` to LinkedIn + Telegram bot + AI (+ optional Gmail/OAuth/worker)
5. Remove Freelancer field codes from `telegram/bot_settings.py` (`fbids`, `bids`, `thr`, `flen`, `flpoll`, `flkw`, `flmin`, `flmax`, Freelancer category)

### Phase 1 — Multi-user data model

Add something like:

```text
User
  id, telegram_user_id (unique), chat_id, username, created_at, is_active

UserLinkedInSettings  (or AppSettings keyed by user_id + key)
  same fields as LinkedInSettings today — one row/blob per user

LinkedInJob
  + user_id  (required)

AtsResume
  + user_id  (or infer via job)

OAuth / Gmail secrets
  scoped per user (never global)
```

Migrate away from global keys:

- `linkedin_settings` → per-user
- `TELEGRAM_REVIEW_CHAT_ID` → only for **admin** alerts (optional); job notifications go to each user’s `chat_id`

### Phase 2 — Telegram as the app

Extend the review bot so any user can:

| Command / menu | Purpose |
|----------------|---------|
| `/start` | Register + welcome + main menu |
| Settings | Per-user LinkedIn + AI + general toggles |
| Upload / paste CV | Store `cv_text` / file path per user |
| Find now | Run find for **this** user only |
| Pending / lists | Their matched jobs |
| Pause / resume | Toggle their `enabled` |

Reuse patterns in:

- `backend/app/telegram/bot.py` — currently single-chat allowlist → change to registered users
- `backend/app/telegram/bot_settings.py` — already has LinkedIn field codes; make load/save **user-scoped**
- `backend/app/telegram/review_actions.py` — ensure callbacks check job ownership
- `backend/app/telegram/keyboards.py`, `lists.py`, `channel_messages.py`

### Phase 3 — Poller per user

Today: `poll_linkedin_jobs` uses one settings blob.

Target:

- Load all active users with `enabled=true`
- For each user due by their interval → `run_linkedin_find(user_id=...)`
- Score against **that user’s** CV / RAG index (per-user vector store or per-user CV text)
- Notify **that user’s** chat only

### Phase 4 — Optional polish

- Admin bot commands (broadcast, disable abusive users)
- Keep or drop web UI; if keep, auth by Telegram or API key per user
- Shared VPS/PC worker queue: include `user_id` on `WorkJob`
- Rate limits: LinkedIn guest scrape courtesy limits across all users

### Monetization (plans)

Sell via Telegram bot (**💎 Plans**):

| Piece | Options |
|-------|---------|
| Duration | 1 / 3 / 6 / 12 months |
| Base | LinkedIn match + notify |
| Add-on | **AI** (screening / compose) — optional, adds to total |
| Add-on | **ATS** (resume scoring / tailor) — optional, adds to total |

Pricing is configured in `.env` (`PLAN_PRICE_*`, `PLAN_AI_ADDON_PER_MONTH`, `PLAN_ATS_ADDON_PER_MONTH`).  
**Payment (now):** card-to-card — set `PAYMENT_CARD_NUMBER` / `PAYMENT_CARD_HOLDER` / `PAYMENT_BANK_NAME`.  
User transfers → sends receipt photo to the bot → admin chat gets receipt + **Activate / Reject**.  
Later optional: Stripe / Telegram Stars.

Entitlements helper: `app.billing.service.user_entitlements` → `has_active_plan`, `include_ai`, `include_ats`.

---

## Settings each user must configure (from current app)

These exist today as global `LinkedInSettings` + bot field codes. Make them **per user**.

### LinkedIn search & matching

| Field | Bot code (today) | Notes |
|-------|------------------|-------|
| `enabled` | `lien` | Search on/off |
| `search_phrases` | `lisp` | Comma-separated queries |
| `location` | `liloc` | Search location |
| `poll_interval_minutes` | `lipoll` | Min ~15 in poller |
| `list_cv_match_threshold` | `lilist` | Notify threshold (default 65) |
| `email_cv_match_threshold` | `liemail` | Send threshold (default 70) |
| `ats_resume_threshold` | `liats` | ATS enqueue (default 75) |
| `test_mode` | `litest` | Find but don’t send Gmail |
| `auto_mailing_enabled` | `limail` | Auto Gmail send |
| `max_emails_per_day` | `limax` | Cap |

### Profile & CV (UI today; expose in bot)

- `applicant_name`, `applicant_role`, `linkedin_email`
- `top_skills`, `experience_summary`
- `cv_text`, `cv_file_path`
- `email_template`

### Gmail (optional)

- `gmail_address`, `gmail_app_password`
- `from_email`, `from_name`
- `notification_email`, `default_recipient_email`

### App-level (today global — decide per-user vs shared)

- Automation / test mode (general)
- AI provider picks (`ai_screening_provider`, etc.)
- Pre-match filters currently shared with Freelancer (`pre_match_filters`) — **fold into LinkedIn user settings** (block phrases, English-only) if still useful; drop Freelancer budget filters

### Env (server-wide, not per user)

- `TELEGRAM_REVIEW_BOT_TOKEN` (the product bot)
- AI API keys (or later: users bring own keys)
- Optional: `LINKEDIN_CLIENT_ID/SECRET` if keeping OpenID connect
- Optional: worker / queue secrets for VPS↔PC split

---

## Architecture to preserve (LinkedIn slice)

```text
poll / find (per user)
  → search_linkedin_jobs (guest HTML)
  → fetch description
  → filters + score_text_relevance (RAG vs user CV)
  → if score ≥ list threshold → LinkedInJob(status=matched, user_id=…)
  → notify user chat (Job Found + buttons)
  → optional ATS if ≥ ats threshold
  → optional Gmail batch if auto_mailing
```

**Key modules (keep):**

```text
backend/app/linkedin/*          # search, service, poller, relevance, settings, email, oauth, cv
backend/app/telegram/bot.py
backend/app/telegram/bot_settings.py
backend/app/telegram/review_actions.py
backend/app/telegram/keyboards.py
backend/app/telegram/lists.py
backend/app/telegram/channel_messages.py   # LinkedIn formatters only
backend/app/rag/*               # CV scoring
backend/app/ats/*               # optional resume feature
backend/app/filters/*           # adapt into per-user LinkedIn filters
backend/app/ai/evaluator.py     # if job_screen / compose need it
backend/app/worker/*            # optional heavy work offload
backend/app/database.py         # extend with User + user_id FKs
backend/app/config.py           # slim env
backend/app/main.py             # slim lifespan
```

**Exclude / delete when stripping:**

```text
backend/app/freelancer/*
Freelancer routes & poll loops
Telethon bid automation in telegram/service.py
Project / DailyBidCount models
deploy/check_freelancer_*, enable_freelancer_poll, apply_freelancer_env
Job Tracker*.bat names → rename later
```

---

## Job statuses (unchanged)

`found` → `matched` → (`draft` | `emailed` | `skipped` | `failed`)

Telegram buttons (keep): **Create email** · **Create resume** · **Skip** (+ Open LinkedIn)

---

## How to run (today’s copied app — until you strip)

```powershell
cd "C:\Users\Ramin\Development\Linkedin Job Finder\backend"
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# edit .env — at minimum TELEGRAM_REVIEW_BOT_TOKEN + AI key
uvicorn app.main:app --reload --port 8000
```

Frontend (optional): `frontend\` Vite app — LinkedIn settings tab exists but is single-user.

---

## Acceptance criteria (done when)

- [ ] No Freelancer bidding / Telethon bid paths required to run
- [ ] Two different Telegram users can `/start`, set different search phrases, and receive different job matches in their own chats
- [ ] Settings edits in bot persist per user and survive restart
- [ ] Jobs/actions cannot be operated by another user (ownership checks)
- [ ] README describes LinkedIn Job Finder only (Telegram-first)
- [ ] Secrets stay out of git (`.env` local only)

---

## Notes for the next agent

1. **Do not** treat the Freelancer automation folder as the workspace — work only in `Linkedin Job Finder`.
2. Prefer small vertical slices: User model + scoped settings → bot `/start` → one-user find → then multi-user poller.
3. Default LinkedIn settings in `linkedin/settings.py` still contain personal defaults (name/CV path for the original author) — replace with empty/generic defaults for a multi-user product.
4. Guest LinkedIn search can break or rate-limit; plan shared courtesy delays when many users poll.
5. This folder was copied **without** `.git`, `venv`, `node_modules`, `data/`, and `.env`. Initialize git when ready; copy `.env.example` → `.env` locally.

---

## Quick file map

| Path | Role |
|------|------|
| `backend/app/linkedin/service.py` | Find / match / process jobs |
| `backend/app/linkedin/poller.py` | Interval polling |
| `backend/app/linkedin/settings.py` | Settings dataclass + DB load/save |
| `backend/app/linkedin/search.py` | Guest job search |
| `backend/app/linkedin/relevance.py` | CV vector score |
| `backend/app/telegram/bot.py` | Bot long-poll |
| `backend/app/telegram/bot_settings.py` | In-bot settings UI |
| `backend/app/telegram/review_actions.py` | Button callbacks |
| `backend/app/main.py` | FastAPI + background loops |
| `frontend/src/App.jsx` | Dashboard (LinkedIn tab) — optional later |

When in doubt, re-read this file and implement the **multi-user Telegram-first** product described above.
