"""AI sticker routes for uploaded (curated) stories.

The generated image lives in ``content/generated/<story_id>/`` — the same tree
the GPIO image button already uses for curated stories — deliberately separate
from the story's own cover image in ``content/stories/<story_id>/``. These
routes never read or write the story's ``cover_image`` field or anything under
``content/stories/``: ``generated_sweeper.sweep_generated`` protects these
cover-only directories while the story exists, and
``app/routers/stories.py::delete_story`` removes them with the story.
"""

import json
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.dependencies import get_story_manager
from app.services.cover_prompt_builder import build as build_cover_prompt
from app.services.story_manager import StoryManager
from app.services.swap_orchestrator import LlamaRelaunchError

router = APIRouter(prefix="/api/stories", tags=["stickers"])

GENERATED_DIR = Path("content/generated")

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _validate_id_or_400(story_id: str) -> None:
    """Reject non-UUID ids with 400 before any filesystem touch."""
    if not _UUID_RE.match(story_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid story id: {story_id!r}",
        )


def _ensure_under_generated_dir(story_id: str) -> None:
    """Resolve target path and assert it lives under GENERATED_DIR (T-16-01)."""
    target = (GENERATED_DIR / story_id).resolve()
    base = GENERATED_DIR.resolve()
    if hasattr(target, "is_relative_to"):
        if not target.is_relative_to(base):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="path traversal rejected",
            )
    else:
        try:
            target.relative_to(base)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="path traversal rejected",
            ) from e


def _sticker_event(event_type: str, data: dict) -> str:
    wrapped = {event_type: data}
    return f"data: {json.dumps(wrapped, ensure_ascii=False)}\n\n"


class StickerRequest(BaseModel):
    hint: str | None = Field(None, max_length=200)


@router.get("/{story_id}/sticker")
def get_sticker(
    story_id: str,
    story_manager: StoryManager = Depends(get_story_manager),
) -> dict:
    """Get the AI sticker image for an uploaded story, if it exists."""
    _validate_id_or_400(story_id)
    _ensure_under_generated_dir(story_id)
    story = story_manager.get_story(story_id)
    if story is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"story '{story_id}' not found",
        )
    print_path = GENERATED_DIR / story_id / "cover-print.png"
    if not print_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no sticker image for story '{story_id}'",
        )
    mtime = print_path.stat().st_mtime
    return {
        "preview_url": f"/static/generated/{story_id}/cover-preview.png",
        "print_url": f"/static/generated/{story_id}/cover-print.png",
        "generated_at": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
    }


@router.post("/{story_id}/sticker")
async def generate_sticker(
    story_id: str,
    body: StickerRequest,
    request: Request,
    story_manager: StoryManager = Depends(get_story_manager),
):
    """Generate an AI sticker image for an uploaded story (SSE).

    The image lands in ``content/generated/<story_id>/`` and the story's own
    ``cover_image`` / ``content/stories/`` are never touched.
    """
    if not getattr(request.app.state, "ai_enabled", False):
        return JSONResponse(
            status_code=503,
            content={"error": "AI not available on this device"},
        )
    orchestrator = getattr(request.app.state, "swap_orchestrator", None)
    if orchestrator is None:
        return JSONResponse(
            status_code=503, content={"error": "cover generation unavailable"}
        )
    _validate_id_or_400(story_id)
    _ensure_under_generated_dir(story_id)
    story = story_manager.get_story(story_id)
    if story is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"story '{story_id}' not found",
        )

    subject = (body.hint or story.title or "").strip()
    if subject:
        positive, negative = build_cover_prompt(
            [{"category": "personaje", "value": subject}]
        )
    else:
        positive, negative = build_cover_prompt([])
    # Random seed (like the GPIO image button) so re-presses produce a
    # different image.
    seed = random.randint(0, 2**32 - 1)

    async def stream():
        # Emit the start event first so the client knows generation began
        # and proxies don't buffer the whole stream.
        yield _sticker_event(
            "sticker_started", {"story_id": story_id, "subject": subject}
        )
        try:
            preview_path, print_path, gen_seconds = (
                await orchestrator.generate_cover_for_story(
                    story_id, positive, negative, seed
                )
            )
        except LlamaRelaunchError:
            print(
                json.dumps(
                    {
                        "event": "sticker_failed",
                        "story_id": story_id,
                        "reason": "llama_relaunch_failed",
                    }
                ),
                file=sys.stderr,
            )
            yield _sticker_event("sticker_failed", {"reason": "llama_relaunch_failed"})
            return
        except Exception as e:
            print(
                json.dumps(
                    {
                        "event": "sticker_failed",
                        "story_id": story_id,
                        "reason": type(e).__name__,
                    }
                ),
                file=sys.stderr,
            )
            yield _sticker_event("sticker_failed", {"reason": type(e).__name__})
            return

        if preview_path is None or print_path is None:
            print(
                json.dumps(
                    {
                        "event": "sticker_failed",
                        "story_id": story_id,
                        "reason": "orchestrator returned None",
                    }
                ),
                file=sys.stderr,
            )
            yield _sticker_event(
                "sticker_failed", {"reason": "orchestrator returned None"}
            )
            return

        print(
            json.dumps(
                {
                    "event": "sticker_generated",
                    "story_id": story_id,
                    "gen_seconds": gen_seconds,
                }
            ),
            file=sys.stderr,
        )
        # Derive the URLs from the actual output filenames (avoids a silent
        # 404 if the worker's basenames ever change).
        yield _sticker_event(
            "sticker_ready",
            {
                "preview_url": f"/static/generated/{story_id}/{preview_path.name}",
                "print_url": f"/static/generated/{story_id}/{print_path.name}",
                "gen_seconds": gen_seconds,
            },
        )

    return StreamingResponse(stream(), media_type="text/event-stream")
