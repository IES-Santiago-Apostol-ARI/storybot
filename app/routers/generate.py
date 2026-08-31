"""Generate router — AI story generation endpoint."""

import asyncio
import json
import random
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings
from app.services.atomic_io import write_json_atomic
from app.services.cover_prompt_builder import build as build_cover_prompt
from app.services.led_animator import Mode
from app.services.led_effects import hex_to_rgb
from app.services.sentence_buffer import SentenceBuffer
from app.services.swap_orchestrator import LlamaRelaunchError

router = APIRouter()

GENERATED_DIR = Path("content/generated")
MAX_GENERATED_STORIES = 5


# LED-20 / D-21 (PLAN DECISION): the in-flight generation progress bar fills in
# a DEFINED NEUTRAL ACCENT — settings.led_accum_color — because during generation
# no story is saved yet (no led_color). Once the story is saved its real
# led_color governs playback (plan 04). Pinned by test_audio_ready_drives_
# progress_mode_with_accum_color so the color is verifiable, not undefined.
def _gen_progress_rgb() -> tuple[int, int, int]:
    return hex_to_rgb(get_settings().led_accum_color)


class StoryParameter(BaseModel):
    model_config = ConfigDict(extra="allow")
    category: str = Field(..., min_length=1)
    value: str = Field(..., min_length=1)


class StoryGenerateRequest(BaseModel):
    parameters: list[StoryParameter]


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
    write_json_atomic(
        story_dir / "story.json", story_data, indent=2, ensure_ascii=False
    )


def _cover_event(event_type: str, data: dict) -> str:
    wrapped = {event_type: data}
    return f"data: {json.dumps(wrapped, ensure_ascii=False)}\n\n"


@router.post("/api/generate/story")
async def generate_story(request: StoryGenerateRequest, fastapi_request: Request):
    if not fastapi_request.app.state.ai_enabled:
        return JSONResponse(
            status_code=503,
            content={"error": "AI not available on this device"},
        )
    if not request.parameters:
        return JSONResponse(status_code=400, content={"error": "parameters required"})

    params = [p.model_dump() for p in request.parameters]

    story_generator = fastapi_request.app.state.story_generator
    tts_pipeline = getattr(fastapi_request.app.state, "tts_pipeline", None)
    story_manager = getattr(fastapi_request.app.state, "story_manager", None)
    orchestrator = getattr(fastapi_request.app.state, "swap_orchestrator", None)
    # Phase 33-05 D-01: reach the engine via the SAFE getattr pattern —
    # tests/test_api/test_generate.py builds TestClient(app) WITHOUT a context
    # manager, so the lifespan never runs and app.state.led_animator is never
    # set; direct attribute access would raise AttributeError (T-33-11). Every
    # call below is None-guarded so a missing engine degrades to no LED
    # feedback rather than breaking the generation stream.
    animator = getattr(fastapi_request.app.state, "led_animator", None)
    # Task 3 (PLAN.md): cap generated stories at MAX_GENERATED_STORIES.
    # Prune BEFORE generating so the new story (saved inside _stream_body)
    # never pushes the total above the limit.
    if story_manager is not None:
        await asyncio.to_thread(
            story_manager.prune_generated, MAX_GENERATED_STORIES - 1
        )

    story_id = str(uuid.uuid4())
    collected_text: list[str] = []
    segments: list[dict] = []
    # One narrator per story: pick the speaker (random M/F for sharvard,
    # per settings.tts_speaker) once and hold it for every segment.
    story_speaker = tts_pipeline.pick_speaker() if tts_pipeline else None

    async def _stream_body():
        buf = SentenceBuffer()
        seg_index = 0
        truncated = False
        start_time = time.monotonic()
        first_token_emitted = False

        async def _synth_and_events(sentence):
            """Synthesize one sentence and yield its SSE event(s).

            Appends the segment meta to ``segments`` and drives the LED
            progress/error modes. Shared by the main loop and the flush path
            (IMPROVEMENTS.md 2.1) — behavior identical in both.
            """
            nonlocal seg_index
            meta = await tts_pipeline.synthesize_segment(
                sentence,
                GENERATED_DIR / story_id,
                index=seg_index,
                speaker_id=story_speaker,
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

            # Task 12: structured timing for TTS segment synthesis.
            print(
                json.dumps(
                    {
                        "event": "gen_segment_synth",
                        "story_id": story_id,
                        "index": meta["index"],
                        "chars": len(meta["text"]),
                        "ms": (time.monotonic() - start_time) * 1000,
                    }
                ),
                file=sys.stderr,
            )

            # LED-20 / D-21 (PLAN DECISION): each audio_ready advances the
            # per-pixel progress bar with RUNNING-KNOWN-COUNT N (i == n each
            # step), in the defined neutral accent (settings.led_accum_color
            # -> _gen_progress_rgb()) because no story led_color exists
            # mid-stream. The bar self-corrects and ends full on the final
            # flush. Driven through the engine, the sole writer. None-guarded.
            if animator is not None:
                animator.set_mode(
                    Mode.PROGRESS,
                    i=seg_index,
                    n=seg_index,
                    color=_gen_progress_rgb(),
                )
            # LED-15 / D-09 / D-15: a per-segment synth error drives the
            # engine into gentle amber error mode (never red, never strobe).
            # The engine auto-fades back (D-16).
            if meta.get("error") and animator is not None:
                animator.set_mode(Mode.ERROR)

        # Self-heal: a prior cover swap that timed out or was cancelled can
        # leave llama-server stopped, which otherwise wedges every later
        # generation with "Failed to connect to llama-server". Bring it back
        # before generating (no-op when already up; skipped mid-swap so it
        # doesn't fight Stable Diffusion for VRAM). None-guarded — T-33-11.
        if orchestrator is not None:
            await orchestrator.ensure_llama_running()

        # LED-17 / D-08: generation start drives the thinking comet through the
        # engine (sole writer). Cross-fades from idle (LED-22, handled by the
        # engine). None-guarded — T-33-11.
        if animator is not None:
            animator.set_mode(Mode.THINKING)

        async for event in story_generator.generate_story(params):
            data = json.dumps(event, ensure_ascii=False)
            yield f"data: {data}\n\n"
            if event.get("text"):
                collected_text.append(event["text"])

                # Task 12: structured timing for first LLM token arrival.
                if not first_token_emitted:
                    first_token_emitted = True
                    print(
                        json.dumps(
                            {
                                "event": "gen_first_token",
                                "story_id": story_id,
                                "ms": (time.monotonic() - start_time) * 1000,
                            }
                        ),
                        file=sys.stderr,
                    )

                # Feed text to sentence buffer
                completed = buf.feed(event["text"])
                for sentence in completed:
                    if tts_pipeline:
                        async for chunk in _synth_and_events(sentence):
                            yield chunk

            # LED-15 / D-09: a stream-level generation error (the LLM/TTS
            # pipeline emitted {"error": ...}) drives the engine into error
            # mode through the sole writer. None-guarded.
            if event.get("error") and animator is not None:
                animator.set_mode(Mode.ERROR)

            if event.get("done"):
                truncated = bool(event.get("truncated"))
                break

        # Flush remaining buffer
        remaining = buf.flush()
        # IMPROVEMENTS.md 3.2: on finish_reason == "length" the buffer tail is
        # a mid-word fragment, not a sentence — drop it from narration and from
        # the saved text (a story ending one sentence early beats one that
        # stops mid-word). All-fragment stories save nothing at all.
        if truncated and remaining:
            fragment = remaining[0]
            remaining = []
            full_text = "".join(collected_text).rstrip()
            if full_text.endswith(fragment):
                full_text = full_text[: -len(fragment)].rstrip()
            collected_text[:] = [full_text] if full_text else []
            print(
                json.dumps(
                    {
                        "event": "story_truncated",
                        "story_id": story_id,
                        "dropped_chars": len(fragment),
                    }
                ),
                file=sys.stderr,
            )
        for sentence in remaining:
            if tts_pipeline:
                async for chunk in _synth_and_events(sentence):
                    yield chunk

        # Kiosk contract (IMPROVEMENTS.md 1.1): every audio segment has now
        # been emitted. The {"text": None, "done": true} sentinel above CANNOT
        # serve as the end-of-audio signal — it arrives before the flushed
        # tail. The kiosk marks its playback queue complete here and keeps
        # reading the stream for cover_ready/cover_failed.
        yield f"data: {json.dumps({'audio_complete': True, 'done': False})}\n\n"

        # Task 12: structured timing for pipeline completion.
        full_text = "".join(collected_text)
        print(
            json.dumps(
                {
                    "event": "gen_complete",
                    "story_id": story_id,
                    "segments": len(segments),
                    "chars": len(full_text),
                    "total_ms": (time.monotonic() - start_time) * 1000,
                    "truncated": truncated,
                }
            ),
            file=sys.stderr,
        )

        if collected_text:
            _save_generated_story(
                story_id,
                "".join(collected_text),
                params,
                GENERATED_DIR,
                segments=segments,
            )

        # Cover generation (after story save, audio fully flushed)
        if collected_text and orchestrator and story_manager:
            positive, negative = build_cover_prompt(params)
            # Random seed (like the GPIO image button and the admin sticker
            # button) so the same parameters never draw the same sticker
            # twice. It used to be crc32(story_id), which made a regeneration
            # of the same story pixel-identical.
            seed = random.randint(0, 2**32 - 1)

            try:
                # The orchestrator bounds the SD worker internally (WORKER_
                # TIMEOUT_S) and always restarts llama in a finally, so it must
                # NOT be wrapped in an external asyncio.wait_for — that cancelled
                # the swap mid-cycle and left llama-server permanently dead.
                result = await orchestrator.generate_cover_for_story(
                    story_id, positive, negative, seed
                )
                preview_path, print_path, gen_seconds = result

                if preview_path and print_path:
                    await asyncio.to_thread(
                        story_manager.attach_cover,
                        story_id,
                        str(preview_path),
                        str(print_path),
                    )
                    # Task 12: structured timing for cover generation.
                    print(
                        json.dumps(
                            {
                                "event": "cover_generated",
                                "story_id": story_id,
                                "gen_seconds": gen_seconds,
                            }
                        ),
                        file=sys.stderr,
                    )
                    yield _cover_event(
                        "cover_ready",
                        {
                            "preview_url": (
                                f"/static/generated/{story_id}/cover-preview.png"
                            ),
                            "print_url": (
                                f"/static/generated/{story_id}/cover-print.png"
                            ),
                            "gen_seconds": gen_seconds,
                        },
                    )
                else:
                    yield _cover_event(
                        "cover_failed", {"reason": "orchestrator returned None"}
                    )
            except LlamaRelaunchError:
                if animator is not None:
                    animator.set_mode(Mode.ERROR)
                yield _cover_event("cover_failed", {"reason": "llama_relaunch_failed"})
            except Exception as e:
                if animator is not None:
                    animator.set_mode(Mode.ERROR)
                yield _cover_event("cover_failed", {"reason": type(e).__name__})

    async def stream():
        """Resilience wrapper around the stream body (IMPROVEMENTS.md 1.4).

        The LED engine only ever leaves THINKING/PROGRESS when someone tells
        it to — on a client disconnect (GeneratorExit) nobody will send the
        'ended' state, and an unexpected exception would kill the SSE with no
        error event. Both paths must reset the engine.
        """
        inner = _stream_body()
        try:
            async for chunk in inner:
                yield chunk
        except GeneratorExit:
            # Kiosk tab closed mid-generation: settle the engine back to idle.
            if animator is not None:
                animator.set_mode(Mode.IDLE)
            raise
        except Exception as e:
            # Unexpected failure (TTS raise, disk error, ...): end the stream
            # with a terminal error event; ERROR mode auto-fades (D-16).
            if animator is not None:
                animator.set_mode(Mode.ERROR)
            yield f"data: {json.dumps({'error': type(e).__name__, 'done': True})}\n\n"
        finally:
            await inner.aclose()

    return StreamingResponse(stream(), media_type="text/event-stream")
