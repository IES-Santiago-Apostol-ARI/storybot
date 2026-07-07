"""Generate router — AI story generation endpoint."""

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.config import ConfigManager
from app.services.cover_prompt_builder import build as build_cover_prompt
from app.services.cover_prompt_builder import story_seed
from app.services.led_animator import Mode
from app.services.led_effects import hex_to_rgb
from app.services.sentence_buffer import SentenceBuffer
from app.services.swap_orchestrator import LlamaRelaunchError

router = APIRouter()

GENERATED_DIR = Path("content/generated")

# LED-20 / D-21 (PLAN DECISION): the in-flight generation progress bar fills in
# a DEFINED NEUTRAL ACCENT — settings.led_accum_color — because during generation
# no story is saved yet (no led_color). Once the story is saved its real
# led_color governs playback (plan 04). Pinned by test_audio_ready_drives_
# progress_mode_with_accum_color so the color is verifiable, not undefined.
_settings = ConfigManager().load()


GEN_PROGRESS_RGB: tuple[int, int, int] = hex_to_rgb(_settings.led_accum_color)


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

            # LED-20 / D-21 (PLAN DECISION): each audio_ready advances the
            # per-pixel progress bar with RUNNING-KNOWN-COUNT N (i == n each
            # step), in the defined neutral accent (settings.led_accum_color
            # -> GEN_PROGRESS_RGB) because no story led_color exists
            # mid-stream. The bar self-corrects and ends full on the final
            # flush. Driven through the engine, the sole writer. None-guarded.
            if animator is not None:
                animator.set_mode(
                    Mode.PROGRESS,
                    i=seg_index,
                    n=seg_index,
                    color=GEN_PROGRESS_RGB,
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

        async for event in story_generator.generate_story(request.parameters):
            data = json.dumps(event, ensure_ascii=False)
            yield f"data: {data}\n\n"
            if event.get("text"):
                collected_text.append(event["text"])

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

        if collected_text:
            _save_generated_story(
                story_id,
                "".join(collected_text),
                request.parameters,
                GENERATED_DIR,
                segments=segments,
            )

        # Cover generation (after story save, audio fully flushed)
        if collected_text and orchestrator and story_manager:
            positive, negative = build_cover_prompt(request.parameters)
            seed = story_seed(story_id)

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
                    story_manager.attach_cover(
                        story_id, str(preview_path), str(print_path)
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
