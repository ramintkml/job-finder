"""Run a CV interview extraction using the PC Codex CLI."""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from pathlib import Path

from app.config import DATA_DIR
from app.services.cv_ai import prompt, validate_analysis
from app.ai.codex import run_codex


async def run_cv_edit(payload: dict) -> dict:
    uid = int(payload['telegram_user_id'])
    request_id = str(payload['request_id'])
    if uid <= 0 or not re.fullmatch(r'[a-f0-9]{32}', request_id):
        raise ValueError('Invalid CV interview request')
    workspace = DATA_DIR / 'worker_cv_edits' / str(uid) / request_id
    workspace.mkdir(parents=True, exist_ok=True)
    system, user = prompt(payload)
    (workspace / 'request.md').write_text(
        system + '\n\nINPUT DATA\n' + user +
        '\n\nReturn only the requested JSON. Do not use tools or read/write files.',
        encoding='utf-8')
    await asyncio.to_thread(run_codex, workspace,
        system + '\n\nUNTRUSTED INPUT DATA\n' + user +
        '\n\nReturn only the requested JSON. Do not use tools or read/write files.',
        workspace / 'RESULT.json', timeout=600)
    result_path = workspace / 'RESULT.json'
    if not result_path.resolve().is_relative_to(workspace.resolve()):
        raise ValueError('CV result escaped workspace')
    if not result_path.is_file() or result_path.stat().st_size > 60000:
        raise ValueError('CV interview agent did not produce a valid result file')
    from app.ai.evaluator import _extract_json
    result = validate_analysis(_extract_json(result_path.read_text(encoding='utf-8')), payload)
    return {'analysis': result}
