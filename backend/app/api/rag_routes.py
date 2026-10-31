from fastapi import APIRouter, HTTPException

from app.rag.indexer import build_profile_index
from app.rag.matcher import index_status, vector_screen_project_async

router = APIRouter(prefix="/rag", tags=["rag"])


@router.get("/status")
def rag_status():
    return index_status()


@router.post("/refresh")
async def rag_refresh():
    try:
        return await build_profile_index()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@router.post("/test")
async def rag_test(body: dict):
    text = body.get("text", "").strip()
    if not text:
        raise HTTPException(400, "text is required")
    result = await vector_screen_project_async(text)
    return {
        "ok": True,
        "action": result.action,
        "confidence": result.confidence,
        "skip_reason": result.skip_reason,
        "review_reason": result.review_reason,
    }
