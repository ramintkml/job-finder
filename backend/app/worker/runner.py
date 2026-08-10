"""PC worker — poll VPS work queue, run heavy jobs, report results.

Telegram (review bot + Telethon) runs on the VPS only.
This worker handles AI/ATS jobs: email compose, resume generate/regenerate.

Usage:
  python -m app.worker.runner

Env (backend/.env or process env):
  WORKER_REMOTE_URL=http://127.0.0.1:8000   # SSH tunnel to VPS
  WORKER_API_SECRET=...
  WORKER_ID=pc-main   (optional)
  WORKER_POLL_SECONDS=3
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid

import httpx

from app.config import settings
from app.worker.execute import execute_job
from app.worker.queue import JOB_PROJECT_SEND, JOB_CODEX_APPLY

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("worker")


def _worker_id() -> str:
    return (settings.worker_id or os.environ.get("WORKER_ID") or "").strip() or (
        f"{socket.gethostname()}-{uuid.getnode():x}"[:64]
    )


def _base_url() -> str:
    return (settings.worker_remote_url or "http://127.0.0.1:8000").rstrip("/")


def _headers() -> dict:
    secret = (settings.worker_api_secret or "").strip()
    if not secret:
        raise SystemExit("WORKER_API_SECRET is required for the PC worker")
    return {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}


def _rag_chroma_ready() -> bool:
    try:
        from app.rag.store import chroma_available, collection_count

        return bool(chroma_available() and collection_count() > 0)
    except Exception:
        return False


async def _heartbeat(client: httpx.AsyncClient, worker_id: str) -> None:
    r = await client.post(
        f"{_base_url()}/api/worker/heartbeat",
        headers=_headers(),
        json={
            "worker_id": worker_id,
            "name": socket.gethostname(),
            "telethon_connected": False,
            "telethon_needs_auth": False,
            "rag_chroma": _rag_chroma_ready(),
        },
        timeout=30,
    )
    r.raise_for_status()


async def _claim(client: httpx.AsyncClient, worker_id: str) -> dict | None:
    r = await client.post(
        f"{_base_url()}/api/worker/claim",
        headers=_headers(),
        json={
            "worker_id": worker_id,
            "telethon_connected": False,
            "telethon_needs_auth": False,
            "rag_chroma": _rag_chroma_ready(),
        },
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    return data.get("job")


async def _complete(client: httpx.AsyncClient, job_id: int, result: dict) -> None:
    r = await client.post(
        f"{_base_url()}/api/worker/jobs/{job_id}/complete",
        headers=_headers(),
        json={"ok": True, "result": result},
        timeout=120,
    )
    r.raise_for_status()


async def _fail(client: httpx.AsyncClient, job_id: int, error: str) -> None:
    r = await client.post(
        f"{_base_url()}/api/worker/jobs/{job_id}/complete",
        headers=_headers(),
        json={"ok": False, "error": error},
        timeout=60,
    )
    r.raise_for_status()


async def run_forever() -> None:
    worker_id = _worker_id()
    poll = max(1.0, float(settings.worker_poll_seconds or 3))
    logger.info(
        "PC worker starting id=%s remote=%s (AI/ATS + vector screen when VPS is lean)",
        worker_id,
        _base_url(),
    )

    async with httpx.AsyncClient(trust_env=False) as client:
        while True:
            try:
                await _heartbeat(client, worker_id)
                job = await _claim(client, worker_id)
                if not job:
                    await asyncio.sleep(poll)
                    continue

                job_id = job["id"]
                job_type = job["job_type"]
                payload = job.get("payload") or {}
                logger.info("Claimed job #%s type=%s entity=%s", job_id, job_type, job.get("entity_id"))

                if job_type == JOB_PROJECT_SEND:
                    await _fail(
                        client,
                        job_id,
                        "Bids run on the VPS now — discard this queued job and use Send bid again",
                    )
                    continue

                try:
                    # Codex apply can take several minutes
                    if job_type == JOB_CODEX_APPLY:
                        logger.info("Running Codex apply bridge for job #%s", job_id)
                    result = await execute_job(job_type, payload)
                    await _complete(client, job_id, result)
                    logger.info("Completed job #%s", job_id)
                except Exception as exc:
                    logger.exception("Job #%s failed", job_id)
                    try:
                        await _fail(client, job_id, str(exc))
                    except Exception:
                        logger.exception("Failed to report job #%s failure", job_id)

            except httpx.HTTPError as exc:
                logger.warning("Worker API error (is the tunnel up?): %s", exc)
                await asyncio.sleep(poll * 2)
            except Exception:
                logger.exception("Worker loop error")
                await asyncio.sleep(poll * 2)


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
