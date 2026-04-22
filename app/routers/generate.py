"""Generate router — AI story generation endpoint."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.services.sentence_buffer import SentenceBuffer

router = APIRouter()

GENERATED_DIR = Path("content/generated")


class StoryGenerateRequest(BaseModel):
    parameters: list[dict[str, Any]]


def _save_generated_story(
    story_id: str,
    text: str,
    parameters: list[dict],
    dest: Path,
    segments: list[dict] | None = None,
) -> None:
    story_dir = dest / story_id
    story_dir.mkdir(parents=True, exist_ok=True)
    story_data = {
        "id": story_id,
        "text": text,
        "parameters": parameters,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if segments is not None:
        story_data["segments"] = segments
    (story_dir / "story.json").write_text(
        json.dumps(story_data, ensure_ascii=False, indent=2)
    )


@router.post("/api/generate/story")
async def generate_story(request: StoryGenerateRequest, fastapi_request: Request):
    if not request.parameters:
        return JSONResponse(status_code=400, content={"error": "parameters required"})

    story_generator = fastapi_request.app.state.story_generator
    tts_pipeline = getattr(fastapi_request.app.state, "tts_pipeline", None)
    story_id = str(uuid.uuid4())
    collected_text: list[str] = []
    segments: list[dict] = []

    async def stream():
        buf = SentenceBuffer()
        seg_index = 0

        for event in story_generator.generate_story(request.parameters):
            data = json.dumps(event, ensure_ascii=False)
            yield f"data: {data}\n\n"
            if event.get("text"):
                collected_text.append(event["text"])

                # Feed text to sentence buffer
                completed = buf.feed(event["text"])
                for sentence in completed:
                    if tts_pipeline:
                        meta = await tts_pipeline.synthesize_segment(
                            sentence,
                            GENERATED_DIR / story_id,
                            index=seg_index,
                        )
                        url = (
                            f"/static/generated/{story_id}/{meta['audio']}"
                            if meta.get("audio")
                            else None
                        )
                        audio_event = {
                            "audio_ready": {
                                "index": meta["index"],
                                "url": url,
                                "text": meta["text"],
                            },
                            "done": False,
                        }
                        if meta.get("error"):
                            audio_event["audio_ready"]["error"] = meta["error"]
                        yield f"data: {json.dumps(audio_event, ensure_ascii=False)}\n\n"
                        segments.append(meta)
                        seg_index += 1

            if event.get("done"):
                break

        # Flush remaining buffer
        remaining = buf.flush()
        for sentence in remaining:
            if tts_pipeline:
                meta = await tts_pipeline.synthesize_segment(
                    sentence,
                    GENERATED_DIR / story_id,
                    index=seg_index,
                )
                url = (
                    f"/static/generated/{story_id}/{meta['audio']}"
                    if meta.get("audio")
                    else None
                )
                audio_event = {
                    "audio_ready": {
                        "index": meta["index"],
                        "url": url,
                        "text": meta["text"],
                    },
                    "done": False,
                }
                if meta.get("error"):
                    audio_event["audio_ready"]["error"] = meta["error"]
                yield f"data: {json.dumps(audio_event, ensure_ascii=False)}\n\n"
                segments.append(meta)
                seg_index += 1

        if collected_text:
            _save_generated_story(
                story_id,
                "".join(collected_text),
                request.parameters,
                GENERATED_DIR,
                segments=segments,
            )

    return StreamingResponse(stream(), media_type="text/event-stream")
