"""OTA update endpoints — check, apply, version."""

import json
import sys

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.models.updates import UpdateCheckResponse, UpdateVersionResponse
from app.services.update_manager import create_update_manager

router = APIRouter(prefix="/api/updates", tags=["updates"])


@router.get("/check", response_model=UpdateCheckResponse)
async def check_update() -> dict:
    """Check if an update is available.

    Returns update_available boolean with local and remote commit info.
    On error, returns update_available false with error message.
    """
    manager = create_update_manager()
    try:
        return await manager.check_update()
    except Exception as e:
        print(
            json.dumps(
                {
                    "event": "update_check_failed",
                    "reason": type(e).__name__,
                }
            ),
            file=sys.stderr,
        )
        return {
            "update_available": False,
            "error": type(e).__name__,
            "local_commit": "unknown",
            "remote_commit": "unknown",
        }


@router.post("/apply")
async def apply_update():
    """Apply available update via git fetch/reset/uv sync.

    Returns SSE stream with stage progress events.
    Concurrent applies return error event (not 409, handled by manager lock).
    """
    manager = create_update_manager()

    async def stream():
        async for event in manager.apply_update():
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/version", response_model=UpdateVersionResponse)
async def get_version() -> dict:
    """Get current application version info.

    Returns version (git describe) and commit (short hash).
    On error, returns 'unknown' for both fields.
    """
    manager = create_update_manager()
    try:
        return await manager.get_version()
    except Exception as e:
        print(
            json.dumps(
                {
                    "event": "version_check_failed",
                    "reason": type(e).__name__,
                }
            ),
            file=sys.stderr,
        )
        return {"version": "unknown", "commit": "unknown"}
