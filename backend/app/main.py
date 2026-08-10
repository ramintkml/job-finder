import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.linkedin_routes import router as linkedin_router
from app.api.pre_match_routes import router as pre_match_router
from app.api.rag_routes import router as rag_router
from app.api.ats_routes import router as ats_router
from app.api.applications_routes import router as applications_router
from app.api.routes import router
from app.config import settings
from app.database import SessionLocal, init_db
from app.telegram.service import telegram_service
from app.worker.api import router as worker_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
FRONTEND_SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"
STATIC_FALLBACK = Path(__file__).resolve().parent / "static"

_PWA_ROOT_FILES = {
    "manifest.webmanifest": "application/manifest+json",
    "sw.js": "application/javascript",
    "favicon.svg": "image/svg+xml",
    "registerSW.js": "application/javascript",
}


def _frontend_index() -> Path | None:
    dist_index = FRONTEND_DIST / "index.html"
    if dist_index.is_file():
        return dist_index
    static_index = STATIC_FALLBACK / "index.html"
    if static_index.is_file():
        return static_index
    return None


def _ui_mode() -> str:
    """Resolve UI mode at call time so deploys work without a full process rebuild."""
    if (FRONTEND_DIST / "index.html").is_file():
        return "dist"
    if (STATIC_FALLBACK / "index.html").is_file():
        return "static"
    return "none"


def _load_persisted_settings() -> None:
    from app.services.settings_service import apply_persisted_settings

    db = SessionLocal()
    try:
        apply_persisted_settings(db)
        telegram_service.set_automation_enabled(settings.automation_enabled)
        # Freelancer bidding removed — keep flag off if still present in settings.
        settings.freelancer_bidding_enabled = False
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _load_persisted_settings()

    async def start_review_bot():
        try:
            from app.telegram.bot import review_bot

            await review_bot.start()
        except Exception:
            logger.exception("Failed to start review bot")

    # Telethon user-client (Freelancer bid bot) is no longer started.
    # LinkedIn auto-search/polling disabled — jobs come from Telegram /apply only.
    asyncio.create_task(start_review_bot())
    asyncio.create_task(_system_alert_loop())
    yield
    try:
        from app.telegram.bot import review_bot

        await review_bot.stop()
    except Exception:
        logger.exception("Failed to stop review bot")


async def _linkedin_poll_loop() -> None:
    """Deprecated: job search polling is disabled (kept for reference / manual revive)."""
    logger.info("LinkedIn poll loop is disabled — skipping")
    return


async def _system_alert_loop() -> None:
    from app.system.alerts import system_alert_loop

    await system_alert_loop()


app = FastAPI(title="LinkedIn Job Finder", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
app.include_router(pre_match_router, prefix="/api")
app.include_router(linkedin_router, prefix="/api")
app.include_router(ats_router, prefix="/api")
app.include_router(applications_router, prefix="/api")
app.include_router(rag_router, prefix="/api")
app.include_router(worker_router, prefix="/api")


@app.api_route("/api/{path:path}", methods=["POST", "PUT", "DELETE", "PATCH"])
def api_write_fallback(path: str):
    """Return 404 (not 405) for unknown write endpoints under /api."""
    raise HTTPException(status_code=404, detail="API endpoint not found")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "telegram_connected": telegram_service.connected,
        "telegram_needs_auth": telegram_service.needs_auth,
        "ui_mode": _ui_mode(),
    }


@app.get("/assets/{file_path:path}")
def frontend_assets(file_path: str):
    path = (FRONTEND_DIST / "assets" / file_path).resolve()
    assets_root = (FRONTEND_DIST / "assets").resolve()
    if not str(path).startswith(str(assets_root)) or not path.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(path)


@app.get("/icons/{filename}")
def frontend_icons(filename: str):
    path = FRONTEND_DIST / "icons" / filename
    if path.is_file():
        return FileResponse(path)
    index = _frontend_index()
    if index:
        return FileResponse(index)
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/{full_path:path}")
def spa(full_path: str):
    if full_path.startswith("api/") or full_path == "api":
        raise HTTPException(status_code=404, detail="Not found")

    index = _frontend_index()
    if not index:
        return {"message": "Frontend not built. Run: cd frontend && npm run build"}

    if full_path:
        # Prefer dist files, then static fallback root files
        for root in (FRONTEND_DIST, STATIC_FALLBACK):
            candidate = root / full_path
            if candidate.is_file():
                media = _PWA_ROOT_FILES.get(candidate.name)
                return FileResponse(candidate, media_type=media) if media else FileResponse(candidate)
        root_name = full_path.split("/")[-1]
        if root_name in _PWA_ROOT_FILES:
            for root in (FRONTEND_DIST, STATIC_FALLBACK):
                root_path = root / root_name
                if root_path.is_file():
                    return FileResponse(root_path, media_type=_PWA_ROOT_FILES[root_name])

    return FileResponse(index)
