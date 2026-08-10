# LinkedIn Job Finder

Telegram-bot-first app (Career Pilot) that finds LinkedIn jobs and helps you apply.

## On your PC

Double-click **`launch.bat`**. It will:

1. Create the Python venv if needed  
2. Open an SSH tunnel to the VPS API/dashboard (`http://127.0.0.1:8000`)  
3. Start the Codex PC worker (Telegram `/apply` → Cursor Agent)  
4. Open the web dashboard in your browser  

Requirements: OpenSSH, SSH key at `%USERPROFILE%\.ssh\ot_clinic_deploy`, `WORKER_API_SECRET` in `backend\.env` (same as VPS), and `agent login` once for Cursor Agent.

## Telegram

- Bottom button: **ارسال آگهی** (paste a JD)  
- Everything else: slash menu beside the text field (`/jobs`, `/account`, `/plans`, …)

## Web dashboard

Focused **Career Pilot** UI (no Freelancer screens):

- Overview — worker / LinkedIn / Gmail status  
- Jobs — find, filter, skip, email  
- Settings — search phrases, Gmail, LinkedIn OAuth  
- ATS — resume scores and downloads  

Open via `launch.bat` → http://127.0.0.1:8000/

```bat
deploy\deploy_to_vps.bat
```

## Not the goal

- Freelancer.com bidding as the primary product  
