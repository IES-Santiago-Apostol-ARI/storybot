"""Generate router — AI story generation endpoint."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

router = APIRouter()

GENERATED_DIR = Path("content/generated")


class StoryGenerateRequest(BaseModel):
    parameters: list[dict[str, Any]]


def _save_generated_story(
    story_id: str, text: str, parameters: list[dict], dest: Path
) -> None:
    story_dir = dest / story_id
    story_dir.mkdir(parents=True, exist_ok=True)
    story_data = {
        "id": story_id,
        "text": text,
        "parameters": parameters,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (story_dir / "story.json").write_text(
        json.dumps(story_data, ensure_ascii=False, indent=2)
    )


@router.post("/api/generate/story")
async def generate_story(request: StoryGenerateRequest, fastapi_request: Request):
    if not request.parameters:
        return JSONResponse(status_code=400, content={"error": "parameters required"})

    story_generator = fastapi_request.app.state.story_generator
    story_id = str(uuid.uuid4())
    collected_text: list[str] = []

    def stream():
        for event in story_generator.generate_story(request.parameters):
            data = json.dumps(event, ensure_ascii=False)
            yield f"data: {data}\n\n"
            if event.get("text"):
                collected_text.append(event["text"])
            if event.get("done"):
                break
        if collected_text:
            _save_generated_story(
                story_id,
                "".join(collected_text),
                request.parameters,
                GENERATED_DIR,
            )

    return StreamingResponse(stream(), media_type="text/event-stream")
