"""Story CRUD API endpoints."""

import json
import shutil
import sys
import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.requests import Request

from app.config import get_settings
from app.dependencies import get_story_manager
from app.models.story import NFCAssignRequest, Story, StoryList
from app.services import transcriber
from app.services.story_manager import StoryManager

router = APIRouter()

# Valid content types
VALID_AUDIO_TYPES = {"audio/mpeg", "audio/wav", "audio/x-wav"}
VALID_COVER_TYPES = {"image/png", "image/jpeg", "image/webp"}

# Extension derived from validated content-type (not client-supplied filename).
_EXT_BY_TYPE: dict[str, str] = {
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}

_CHUNK_SIZE = 1024 * 1024  # 1 MiB


def _save_upload(upload: UploadFile, dest: Path, max_bytes: int) -> None:
    """Copy upload to dest in chunks; abort with 413 if size exceeded.

    Deletes any partial file on failure so the story directory stays clean.
    """
    written = 0
    with dest.open("wb") as f:
        while True:
            chunk = upload.file.read(_CHUNK_SIZE)
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                f.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail=f"Upload exceeds {max_bytes // (1024 * 1024)} MB limit",
                )
            f.write(chunk)


async def _transcribe_story_audio(
    story_manager: StoryManager, story_id: str, audio_path: Path
) -> None:
    """Background task: transcribe uploaded audio and store the transcript.

    Any failure is logged and swallowed — the upload must never break.
    """
    try:
        text = await transcriber.transcribe(audio_path)
    except Exception as exc:  # noqa: BLE001 — background task must not raise
        print(
            json.dumps({"event": "transcribe_task_failed", "error": str(exc)}),
            file=sys.stderr,
        )
        return
    if text:
        story_manager.update_story(story_id=story_id, transcript=text)


# NFC lookup endpoint MUST be defined before /{story_id} to avoid path conflicts
@router.get("/api/stories/nfc/{nfc_uid}", response_model=Story)
def get_story_by_nfc(
    nfc_uid: str,
    story_manager: StoryManager = Depends(get_story_manager),
) -> Story:
    """Get a story by NFC card UID.

    Args:
        nfc_uid: NFC card UID
        story_manager: StoryManager instance

    Returns:
        Story object

    Raises:
        HTTPException: If no story mapped to this NFC card
    """
    story = story_manager.get_story_by_nfc(nfc_uid)
    if not story:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No story mapped to this NFC card",
        )
    return story


@router.post("/api/stories/{story_id}/nfc", response_model=Story)
def assign_nfc_to_story(
    story_id: str,
    request: NFCAssignRequest,
    story_manager: StoryManager = Depends(get_story_manager),
) -> Story:
    """Assign an NFC card UID to a story.

    Args:
        story_id: Story ID
        request: NFC assignment request with nfc_uid
        story_manager: StoryManager instance

    Returns:
        Updated Story object

    Raises:
        HTTPException: If story not found
    """
    story = story_manager.assign_nfc(story_id, request.nfc_uid)
    if not story:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Story '{story_id}' not found",
        )
    return story


@router.post("/api/stories", response_model=Story, status_code=status.HTTP_201_CREATED)
def create_story(
    request: Request,
    background_tasks: BackgroundTasks,
    title: str = Form(...),
    emoji: str = Form(...),
    led_color: str = Form(...),
    audio: UploadFile = File(...),
    cover: UploadFile | None = File(None),
    story_manager: StoryManager = Depends(get_story_manager),
) -> Story:
    """Create a new story with audio file and optional cover image.

    Args:
        request: FastAPI request
        title: Story title
        emoji: Story emoji icon
        led_color: LED color in hex format
        audio: Audio file upload
        cover: Optional cover image upload
        story_manager: StoryManager instance

    Returns:
        Created Story object

    Raises:
        HTTPException: If audio file is invalid or missing
    """
    settings = get_settings()

    # Validate audio content type
    if audio.content_type not in VALID_AUDIO_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid audio type. Must be one of: {VALID_AUDIO_TYPES}",
        )

    # Validate audio filename is present
    if not audio.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Audio file name is required",
        )

    # Generate UUID for story
    story_id = str(uuid.uuid4())

    # Create story directory
    story_dir = Path("content/stories") / story_id
    story_dir.mkdir(parents=True, exist_ok=True)

    # Save audio file (extension from content-type, not filename)
    audio_ext = _EXT_BY_TYPE[audio.content_type]
    audio_path = story_dir / f"audio{audio_ext}"
    _save_upload(audio, audio_path, settings.max_audio_upload_mb * 1024 * 1024)

    # Save cover image if provided
    cover_filename = None
    if cover:
        if cover.content_type not in VALID_COVER_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid cover type. Must be one of: {VALID_COVER_TYPES}",
            )
        cover_ext = _EXT_BY_TYPE[cover.content_type]
        cover_path = story_dir / f"cover{cover_ext}"
        _save_upload(cover, cover_path, settings.max_cover_upload_mb * 1024 * 1024)
        cover_filename = f"cover{cover_ext}"

    # Create story in manager
    story = story_manager.create_story(
        id=story_id,
        title=title,
        emoji=emoji,
        led_color=led_color,
        audio_file=f"audio{audio_ext}",
        cover_image=cover_filename,
    )

    background_tasks.add_task(
        _transcribe_story_audio, story_manager, story_id, audio_path
    )

    return story


@router.put("/api/stories/{story_id}", response_model=Story)
def update_story(
    story_id: str,
    background_tasks: BackgroundTasks,
    title: str = Form(...),
    emoji: str = Form(...),
    led_color: str = Form(...),
    audio: UploadFile | None = File(None),
    cover: UploadFile | None = File(None),
    remove_cover: bool = Form(False),
    story_manager: StoryManager = Depends(get_story_manager),
) -> Story:
    """Update a story's metadata and/or files.

    Args:
        story_id: Story ID to update
        title: Story title
        emoji: Story emoji icon
        led_color: LED color in hex format
        audio: Optional new audio file upload
        cover: Optional new cover image upload
        remove_cover: If True, remove the cover image
        story_manager: StoryManager instance

    Returns:
        Updated Story object

    Raises:
        HTTPException: If story not found or audio file is invalid
    """
    settings = get_settings()

    # Verify story exists first
    existing_story = story_manager.get_story(story_id)
    if not existing_story:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Story '{story_id}' not found",
        )

    story_dir = Path("content/stories") / story_id

    # Handle audio file replacement
    audio_file = existing_story.audio_file
    if audio:
        # Validate audio content type
        if audio.content_type not in VALID_AUDIO_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid audio type. Must be one of: {VALID_AUDIO_TYPES}",
            )

        # Save new audio file (extension from content-type)
        audio_ext = _EXT_BY_TYPE[audio.content_type]
        new_audio_path = story_dir / f"audio{audio_ext}"
        _save_upload(audio, new_audio_path, settings.max_audio_upload_mb * 1024 * 1024)
        audio_file = f"audio{audio_ext}"

        # Delete old audio file if extension changed
        old_audio_path = story_dir / existing_story.audio_file
        if old_audio_path.exists() and old_audio_path != new_audio_path:
            old_audio_path.unlink()

        # Re-transcribe the replaced audio
        background_tasks.add_task(
            _transcribe_story_audio, story_manager, story_id, new_audio_path
        )

    # Handle cover image replacement/removal
    cover_image = existing_story.cover_image
    if cover:
        if cover.content_type not in VALID_COVER_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid cover type. Must be one of: {VALID_COVER_TYPES}",
            )
        cover_ext = _EXT_BY_TYPE[cover.content_type]
        new_cover_path = story_dir / f"cover{cover_ext}"
        _save_upload(cover, new_cover_path, settings.max_cover_upload_mb * 1024 * 1024)
        cover_image = f"cover{cover_ext}"

        # Delete old cover file if extension changed
        if existing_story.cover_image:
            old_cover_path = story_dir / existing_story.cover_image
            if old_cover_path.exists() and old_cover_path != new_cover_path:
                old_cover_path.unlink()
    elif remove_cover:
        # Delete cover file if exists
        if existing_story.cover_image:
            old_cover_path = story_dir / existing_story.cover_image
            if old_cover_path.exists():
                old_cover_path.unlink()
        cover_image = None

    # Update story in manager
    # Pass remove_cover flag to manager
    story = story_manager.update_story(
        story_id=story_id,
        title=title,
        emoji=emoji,
        led_color=led_color,
        audio_file=audio_file,
        cover_image=cover_image,
        remove_cover=remove_cover,
    )

    return story


@router.get("/api/stories", response_model=StoryList)
def list_stories(
    story_manager: StoryManager = Depends(get_story_manager),
) -> StoryList:
    """List all stories.

    Args:
        story_manager: StoryManager instance

    Returns:
        StoryList with stories and total count
    """
    stories = story_manager.list_stories()
    return StoryList(stories=stories, total=len(stories))


@router.get("/api/stories/{story_id}", response_model=Story)
def get_story(
    story_id: str,
    story_manager: StoryManager = Depends(get_story_manager),
) -> Story:
    """Get a single story by ID.

    Args:
        story_id: Story ID
        story_manager: StoryManager instance

    Returns:
        Story object

    Raises:
        HTTPException: If story not found
    """
    story = story_manager.get_story(story_id)
    if not story:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Story '{story_id}' not found",
        )
    return story


@router.delete("/api/stories/{story_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_story(
    story_id: str,
    request: Request,
    story_manager: StoryManager = Depends(get_story_manager),
) -> None:
    """Delete a story by ID.

    Args:
        story_id: Story ID
        request: FastAPI request
        story_manager: StoryManager instance

    Raises:
        HTTPException: If story not found
    """
    # Delete from manager
    deleted = story_manager.delete_story(story_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Story '{story_id}' not found",
        )

    # Delete story directory
    story_dir = Path("content/stories") / story_id
    if story_dir.exists():
        shutil.rmtree(story_dir)

    # The GPIO cover button writes cover-preview.png / cover-print.png to
    # content/generated/<story_id>/ for curated stories too. Nothing else ever
    # cleans that up (sweep_generated and prune_generated both skip dirs
    # without story.json), so remove it with the story.
    story_manager.delete_generated(story_id)
