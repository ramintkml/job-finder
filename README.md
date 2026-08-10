# LinkedIn Job Finder (Career Pilot)

Telegram-first app that finds LinkedIn jobs, scores them against your CV, and helps you apply with tailored ATS resumes and Gmail outreach.

This repository is **LinkedIn / Career Pilot only** — Freelancer.com bidding is not part of this product.

## Features

- **LinkedIn job discovery** — guest search, relevance scoring, and per-user notify flow
- **Telegram bot** — paste a JD, review matches, apply actions (`/jobs`, `/account`, `/plans`, …)
- **ATS pipeline** — tailor resumes to a job description, score fit, export PDF/DOCX
- **Web dashboard** — overview, jobs, settings (search phrases, Gmail, LinkedIn OAuth), ATS downloads
- **PC worker** — heavy apply work via Cursor Agent over an SSH tunnel to the VPS API

## Quick start (PC)

Double-click **`launch.bat`**. It will:

1. Create the Python venv if needed
2. Open an SSH tunnel to the VPS API/dashboard (`http://127.0.0.1:8000`)
3. Start the Codex PC worker (Telegram `/apply` → Cursor Agent)
4. Open the web dashboard in your browser

**Requirements**

- OpenSSH
- SSH key at `%USERPROFILE%\.ssh\ot_clinic_deploy`
- `WORKER_API_SECRET` in `backend\.env` (same value as on the VPS)
- `agent login` once for Cursor Agent

Copy `backend\.env.example` → `backend\.env` and fill in Telegram, AI, and LinkedIn/Gmail settings.

## Telegram

- Bottom button: **ارسال آگهی** (paste a job description)
- Slash menu: `/jobs`, `/account`, `/plans`, and related commands

## Web dashboard

Open via `launch.bat` → [http://127.0.0.1:8000/](http://127.0.0.1:8000/)

| Area | Purpose |
|------|---------|
| Overview | Worker / LinkedIn / Gmail status |
| Jobs | Find, filter, skip, email |
| Settings | Search phrases, Gmail, LinkedIn OAuth |
| ATS | Resume scores and downloads |

## Deploy (VPS)

```bat
deploy\deploy_to_vps.bat
```

See `deploy\` for VPS setup, ecosystem config, and health-check scripts. Use `deploy\vps.env.template` for server env vars.

## Project layout

```text
backend/     FastAPI API, Telegram bot, LinkedIn, ATS, billing, worker
frontend/    Career Pilot dashboard (Vite + React)
deploy/      VPS deploy scripts and templates
launch.bat   Local tunnel + worker + dashboard
```

## Agent context

New Cursor agents: start from [`AGENT_BRIEF.md`](AGENT_BRIEF.md).
