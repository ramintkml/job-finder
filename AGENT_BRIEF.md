# Agent brief

Read README.md for the current product, setup and upgrade procedure.

## Current scope

Career Pilot is a Telegram-first, multi-user application assistant. Users paste
job descriptions/LinkedIn URLs, maintain a personal base CV and receive tailored
resumes. Automatic LinkedIn polling is disabled. Legacy search, Gmail, OAuth,
ATS job tables and shared RAG are operator-only, protected by admin authentication.
Do not describe automatic job discovery as an active background feature.

## Invariants

- Keep all user work inside this repository. Do not modify the original Freelancer fork.
- A Telegram user must never access another user's applications or CV files.
- Bot CV/account operations run only in private chats. Admin access requires an
  exact configured user ID; suffix matches and group IDs are not authorization.
- Base CV facts come from the user. Never inject fixed personal projects, links,
  employers, dates or metrics. Free-text updates require preview and confirmation.
- Saved CVs are per Telegram ID and revisioned; pending previews are ephemeral.
- All generative AI uses ai/codex.py and Codex CLI exclusively. No alternative
  provider or Cursor fallback is allowed, including persisted legacy settings.
- CV entry interviews use services/cv_ai.py and worker/cv_edit.py on Codex.
  Require evidence, ask missing fields and confirm a full
  preview. Match session/request IDs before applying delayed AI results. Never
  turn planned work into completed achievements or save on an AI response alone.
- Worker identity/ownership comes from the queued payload, not generated output.
- Claims are atomic and have an expiring claim token. Completion must identify
  the worker and claim. Do not accept completion of unclaimed/pending work.
- Shared/legacy APIs must remain admin-only. New user-facing API endpoints must
  derive identity from the authenticated session, never a user-supplied ID.
- Do not enable Freelancer bidding, Telethon login, global polling or unsolicited
  application delivery while repairing this product.
- Preserve the user's existing uncommitted changes. Never print .env contents or keys.

## Check changes

Run `python -m unittest discover -s backend/tests -v` with `PYTHONPATH=backend`,
and `npm run build --prefix frontend`. Tests must not contact Telegram, AI services
or the production database. Add meaningful regression coverage for access,
ownership, concurrency and CV data preservation.

Deploy backend and PC worker together after queue protocol changes. Back up the
entire data directory including hidden credential/session keys before
schema changes. The former project brief was a planning snapshot and has been
replaced by this description of the implemented application.
