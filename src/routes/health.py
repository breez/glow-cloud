from datetime import datetime, timezone

from fastapi import APIRouter

from src.services.sdk import is_sdk_initialized

router = APIRouter()


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "sdk_initialized": is_sdk_initialized(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
