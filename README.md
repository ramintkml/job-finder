# Career Pilot

Telegram-first job application assistant. Send a job description or LinkedIn URL,
evaluate it against your own base CV, and generate a tailored resume and ATS feedback.

Automatic LinkedIn polling is **disabled**. The optional legacy search, Gmail,
LinkedIn OAuth and shared RAG tools are **operator/admin-only**. Normal users use
their own CV, application records and isolated worker runs. Freelancer bidding is retired.

## Telegram workflow

- `/start`: create your account.
- `/basecv`: download your current base CV as DOCX and PDF. The menu also supports
  saving a replacement CV, adding a project, work experience or a skill.
- `/addproject` or **➕ افزودن پروژه**: describe the project naturally in Persian
  or English. AI extracts supported facts, asks up to three follow-up questions
  per round, and phrases the entry in the language of your base CV. Review the
  preview, then press **✅ ذخیره**. You can reply with corrections before saving.
  **اطلاعات بیشتری ندارم** skips optional details; a project name and your own
  contribution (including clearly planned work) are still required. No metrics,
  dates, links or experience should be invented.
- To save the first CV, use **📤 ذخیره رزومه پایه** and send DOCX or plain text.
- `/apply`: paste a job description or LinkedIn URL. AI features require the
  appropriate subscription; administrators can use them directly.

Example project entry:

```text
Clinic Scheduling Portal
Role: Backend developer, October 2026–present
Built appointment APIs using Python and PostgreSQL.
Implemented role-based access for clinic staff.
Link: https://example.com
```

The same interview is available for work experience and skills. Replacing the
whole CV remains a direct DOCX/plain-text upload.

Edits require confirmation and preserve the previous CV in
`data/user_cvs/<telegram_id>/history/`. New applications use the updated
CV; already-generated resumes remain historical outputs. Editing an entry or
replacing the whole CV is available through **📤 ذخیره رزومه پایه**. Pending
previews expire on bot restart; confirmed edits persist.

## Local setup

Use Python 3.11+ and Node.js 20+.

```powershell
python -m venv backend/venv
backend/venv/Scripts/python.exe -m pip install -r backend/requirements-vps.txt
Copy-Item backend/.env.example backend/.env
npm ci --prefix frontend
npm run build --prefix frontend
```

Configure `backend/.env`:

- `TELEGRAM_REVIEW_BOT_TOKEN`
- `TELEGRAM_ADMIN_IDS` (explicit Telegram user IDs; group IDs cannot grant admin)
- `WORKER_API_SECRET` (same strong secret on server and PC)
- `DASHBOARD_ADMIN_PASSWORD` (a separate strong password for web sign-in)
- `CODEX_MODEL` optionally selects one Codex model for all AI tasks
- `CODEX_EXECUTION_MODE=queue` on the VPS (`auto` locally)

`launch.bat` starts the SSH tunnel and PC worker. Codex CLI must be installed
and signed in using `codex login`. The bundled Windows Codex Desktop CLI is also
detected when it is not on PATH. `JOB_SEARCH_WORKSPACE` points to the operator's
existing Job Search folder. On worker heartbeat, its `documents/base_cv.txt` is
copied to the first configured administrator **only if that user's saved CV is
missing**. Later Telegram edits take precedence. If multiple admins need separate
CVs, each should upload their own CV in the bot.

Worker runs live under `data/worker_workspaces/<telegram_id>/<run_id>/`.
They receive only that user's CV; personal projects and contact details are not
injected from a fixed operator template. Candidate text and job postings are
untrusted input. The worker uses `codex exec` in a separate run workspace with the
read-only sandbox. Codex returns structured content; Python writes controlled
resume files and exports DOCX/PDF. The model does not need file-write tools. Use a dedicated OS account/container for an untrusted public service.
Personal Codex configuration/plugins are not loaded for application runs; CLI
authentication remains available. No unsandboxed fallback is used.

## AI routing

All generative AI runs through **Codex CLI**: resume creation/improvement,
project interviews, translation, fit evaluation, keyword extraction, email
composition and AI connection tests. There is no Cursor, Groq, Gemini, Claude,
DeepSeek or direct model-API fallback. Legacy provider settings cannot reactivate
these backends. Old credentials may remain in a private .env/database but are
never used by the AI transport.

`CODEX_MODEL` selects one model for all roles. When blank, the CLI's built-in
default is used; no fixed model is claimed. Runs force the OpenAI Codex provider
and ignore personal CLI configuration. Authentication uses the existing Codex
login, without storing API credentials in the application's settings.

The PC worker executes Codex locally. A server without the CLI queues `codex_text`
requests to that worker, even when heavy-queue mode is disabled. On the VPS,
`CODEX_EXECUTION_MODE=queue` makes this explicit. A missing/offline worker produces
an actionable error; it does not silently switch to another model provider.
The queue carries the selected model to the worker for each request.

CV interviews remain owner-scoped `cv_edit` tasks. An offline worker shows a
clear notice; launch `launch.bat` to process the interview. Errors retain answers
and offer retry; cancelled/replaced session results are ignored. Bot restart
expires pending interviews. Each save button confirms exactly its own preview.

Retrieval uses deterministic TF-IDF; optional neural embedding models have been
retired. Existing Chroma-only indexes must be rebuilt via the admin index-refresh
action if the legacy retrieval tools are used. ATS scores remain deterministic
application calculations, without a separate AI provider.

Only the current entry conversation and target CV language are sent for an
interview; the full CV is not sent. AI output must include user quotations for
facts, and unsupported numeric claims/links are rejected. Final factual review
and save confirmation remain with the user.

## Dashboard and API

The web dashboard requires sign-in. Administrator login uses
`DASHBOARD_ADMIN_PASSWORD`; an unset password fails closed. Telegram Mini App
launch data can authenticate an existing active Telegram user; that user can
only see, download and delete their own applications. Shared settings and
operator integrations are restricted to administrators.

Sessions use HttpOnly, SameSite cookies. Use HTTPS for public deployment. Workers
use Bearer authentication plus a per-claim token; the shared worker credential
is not a dashboard password. Cross-origin browser writes are rejected.

## Deployment and upgrade

Push to `master` to run **Verify and Deploy** in GitHub Actions. The workflow
runs all regression tests, builds the dashboard, packages the exact commit and
only then deploys it to the VPS. Manual runs are available through
`workflow_dispatch`. Pull requests run verification without accessing deployment
secrets.

Repository Actions secrets: `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`,
`VPS_KNOWN_HOSTS`. The dedicated SSH key is restricted to this app's deployment
entrypoint. The ordinary administrator SSH key is never uploaded to GitHub.

The server preserves `.env` and runtime data, refuses upgrades while a worker job
is active, and backs up data, credential keys, environment and previous source
under `.deploy/backups/`. Failed activation restores the previous release. A
successful deploy verifies the health revision, Codex engine, dashboard and API
authentication. Releases are serialized with a server lock and Actions concurrency.

On first upgrade a missing dashboard password is generated privately at
`data/dashboard-admin-password.txt`; it is never printed in Actions logs.
`/api/health` reports `revision` for verifying the deployed commit.

Deploy the **server and PC worker together**: old workers cannot complete jobs
without the new claim token. Stop the worker and wait for active tasks to finish
before upgrading. Relaunch `launch.bat` afterward. No deployment is performed by
running the regression tests.

Back up `data/` before upgrading, including the database and hidden
`.credentials_key` and `.session_key`. Gmail passwords and LinkedIn access/refresh
tokens are encrypted on save and migrated on read. Losing `.credentials_key`
makes those stored credentials unreadable. Keep backups private.

Database upgrades add columns and record a schema version without deleting old
records. Legacy LinkedIn/ATS records remain operator-only. Queue claims use an
atomic conditional update, reject stale results and stop retrying after three
abandoned claims. Interrupted result application is flagged for manual review
instead of replaying possible external side effects.

## Verification

```powershell
$env:PYTHONPATH='backend'
backend/venv/Scripts/python.exe -m unittest discover -s backend/tests -v
npm run build --prefix frontend
```

Tests use temporary databases and mock external delivery. They cover access
control, user isolation, CV edits/history, real DOCX/PDF exports, credential
storage, migration repeatability, worker contention and stale completions.

## Layout

```text
backend/app/api/          API, dashboard sessions and access checks
backend/app/telegram/     Bot commands, CV menus and review actions
backend/app/services/     CV persistence and credential encryption
backend/app/ats/          Resume generation, parsing, scoring and export
backend/app/worker/       Queue, PC worker and application delivery
backend/tests/            Offline regression suite
frontend/                React dashboard
deploy/                 VPS setup and deployment
```
