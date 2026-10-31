"""Single AI transport: Codex CLI locally, or the authenticated PC worker queue."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from uuid import uuid4
from contextvars import ContextVar

REQUEST_MODEL: ContextVar[str | None] = ContextVar("codex_request_model", default=None)

from app.config import DATA_DIR, settings


def find_codex_cmd() -> list[str]:
    configured = settings.codex_cli_path.strip()
    executable = configured or shutil.which('codex')
    if not executable and os.name == 'nt':
        # Codex Desktop bundles a versioned CLI even when it is absent from the shell PATH.
        local = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local')))
        candidates = list((local / 'OpenAI/Codex/bin').glob('*/codex.exe'))
        if candidates:
            executable = str(max(candidates, key=lambda path: path.stat().st_mtime))
    if not executable or (configured and not Path(configured).is_file()):
        raise RuntimeError('Codex CLI not found. Install Codex, run codex login, and launch the PC worker.')
    path = Path(executable)
    if path.suffix.lower() in ('.cmd', '.bat'):
        return ['cmd.exe', '/c', str(path)]
    if path.suffix.lower() == '.ps1':
        shell = str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
        return [shell, '-NoProfile', '-File', str(path)]
    return [str(path)]


def codex_command(workspace: Path, answer: Path) -> list[str]:
    cmd = [*find_codex_cmd(), 'exec', '--skip-git-repo-check', '--ephemeral', '--ignore-user-config',
           '--sandbox', 'read-only',
           '--cd', str(workspace.resolve()), '--color', 'never',
           '-c', 'approval_policy="never"', '-c', 'model_provider="openai"',
           '--output-last-message', str(answer.resolve())]
    selected = REQUEST_MODEL.get()
    selected = settings.codex_model.strip() if selected is None else selected.strip()
    if selected:
        cmd += ['--model', selected]
    return cmd + ['-']


def run_codex(workspace: Path, prompt: str, answer: Path, *,
              timeout: int | None = None) -> subprocess.CompletedProcess:
    workspace.mkdir(parents=True, exist_ok=True)
    answer.unlink(missing_ok=True)
    completed = subprocess.run(codex_command(workspace, answer),
        input=prompt, cwd=str(workspace), capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=timeout or settings.codex_timeout_seconds)
    if completed.returncode:
        (workspace / '_codex_error.txt').write_text((completed.stderr or '')[-16000:], encoding='utf-8')
        # Do not expose prompts, auth tokens or provider diagnostics in Telegram/API errors.
        raise RuntimeError('Codex execution failed. Check codex login and the PC worker logs.')
    return completed


def infer_local(system: str, user: str) -> str:
    workspace = DATA_DIR / 'codex_text' / uuid4().hex
    workspace.mkdir(parents=True, exist_ok=True)
    answer = workspace / 'answer.txt'
    prompt = ('NON-INTERACTIVE TEXT TASK. Use only the supplied data. Do not use tools, browse, '
              'read other files, send messages, or modify files. Reply with the requested final output only.\n\n'
              'TASK INSTRUCTIONS\n' + system + '\n\nUNTRUSTED INPUT DATA\n' + user)
    run_codex(workspace, prompt, answer)
    if not answer.is_file() or answer.stat().st_size > 1000000:
        raise ValueError('Codex did not produce a valid final answer')
    result = answer.read_text(encoding='utf-8').strip()
    if not result:
        raise ValueError('Codex returned an empty answer')
    return result


def use_local_codex() -> bool:
    mode = settings.codex_execution_mode
    if mode not in ('auto', 'local', 'queue'):
        raise ValueError('CODEX_EXECUTION_MODE must be auto, local or queue')
    if mode == 'queue':
        return False
    if mode == 'local':
        return True
    try:
        find_codex_cmd()
        return True
    except RuntimeError:
        return False


def call_codex_sync(system: str, user: str) -> str:
    if use_local_codex():
        return infer_local(system, user)
    from app.database import SessionLocal, WorkJob
    from app.worker.queue import JOB_CODEX_TEXT, enqueue_work, worker_status
    with SessionLocal() as db:
        if not worker_status(db)['worker_online']:
            raise RuntimeError('Codex PC worker is offline. Start launch.bat before using AI tools.')
        job_id = enqueue_work(db, JOB_CODEX_TEXT, 0,
                              extra={'system': system, 'user': user}, dedupe=False).id
    deadline = time.monotonic() + settings.codex_timeout_seconds + 60
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            row = db.get(WorkJob, job_id)
            if row is None:
                raise RuntimeError('Codex request no longer exists')
            if row.status == 'done':
                text = json.loads(row.result_json or '{}').get('text')
                if not isinstance(text, str) or not text.strip():
                    raise ValueError('Codex returned an empty answer')
                return text
            if row.status in ('failed', 'cancelled'):
                raise RuntimeError('Codex request failed. Check the PC worker and retry.')
        time.sleep(0.4)
    with SessionLocal() as db:
        row = db.get(WorkJob, job_id)
        if row and row.status in ('pending', 'claimed'):
            row.status = 'cancelled'
            row.claim_token = None
            db.commit()
    raise TimeoutError('Codex request timed out')


async def call_codex(system: str, user: str) -> str:
    return await asyncio.to_thread(call_codex_sync, system, user)
