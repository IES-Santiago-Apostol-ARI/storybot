"""REST routes for admin curation of generated stories (D-10..D-12)."""

import json
import re

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_story_manager
from app.models.generated import PromoteRequest
from app.models.story import Story
from app.services.story_manager import StoryManager

router = APIRouter(prefix="/api/generated", tags=["generated"])

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


def _ensure_under_generated_dir(story_manager: StoryManager, story_id: str) -> None:
    """Resolve target path and assert it lives under GENERATED_DIR (T-16-01)."""
    target = (story_manager.GENERATED_DIR / story_id).resolve()
    base = story_manager.GENERATED_DIR.resolve()
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


@router.get("")
async def list_generated(
    story_manager: StoryManager = Depends(get_story_manager),
) -> dict:
    """List all generated story summaries."""
    rows = story_manager.list_generated()
    return {"stories": rows, "total": len(rows)}


@router.get("/{story_id}")
async def get_generated(
    story_id: str,
    story_manager: StoryManager = Depends(get_story_manager),
) -> dict:
    """Get full detail for a single generated story."""
    _validate_id_or_400(story_id)
    _ensure_under_generated_dir(story_manager, story_id)
    target = story_manager.GENERATED_DIR / story_id
    story_file = target / "story.json"
    if not story_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"generated story '{story_id}' not found",
        )
    return json.loads(story_file.read_text(encoding="utf-8"))


@router.delete("/{story_id}", status_code=status.HTTP_204_NO_CONTENT)
async def discard_generated(
    story_id: str,
    story_manager: StoryManager = Depends(get_story_manager),
) -> None:
    """Delete a generated story directory."""
    _validate_id_or_400(story_id)
    _ensure_under_generated_dir(story_manager, story_id)
    ok = story_manager.delete_generated(story_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"generated story '{story_id}' not found",
        )


@router.post("/{story_id}/promote", status_code=status.HTTP_201_CREATED)
async def promote_generated(
    story_id: str,
    body: PromoteRequest,
    story_manager: StoryManager = Depends(get_story_manager),
) -> Story:
    """Promote a generated story to the curated library."""
    _validate_id_or_400(story_id)
    _ensure_under_generated_dir(story_manager, story_id)
    try:
        return story_manager.promote_generated(
            generated_id=story_id,
            title=body.title,
            emoji=body.emoji,
            led_color=body.led_color,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
