"""NFC router with SSE endpoints for card tap events.

NFC Integration Flow:
---------------------

Admin Panel (Teacher):
    1. EventSource('/api/nfc/read') connects to SSE stream
    2. On 'card' event with UID, display prompt to assign card
    3. POST /api/stories/{id}/nfc with {"nfc_uid": "..."} to assign
    4. Story is now linked to the physical NFC card

Kiosk (Child):
    1. EventSource('/api/nfc/read') connects to SSE stream
    2. On 'card' event with UID, GET /api/stories/nfc/{uid}
    3. If story found, trigger playback with LED feedback
    4. Child hears their personalized story

Card Type Routing (v1.2):
    - story cards: existing playback flow, clear session
    - parameter cards: add to session buffer, emit enriched SSE
    - go cards: emit session params, clear session
    - unknown cards: emit card_type="unknown"
"""

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import EventSourceResponse
from sse_starlette import EventSourceResponse as SSEStarletteResponse

from app.dependencies import get_hardware, get_story_manager
from app.services.hardware_manager import HardwareManager
from app.services.led_animator import Mode
from app.services.session_manager import SessionManager
from app.services.story_manager import StoryManager

router = APIRouter(prefix="/api/nfc", tags=["nfc"])

# Global session — one kiosk = one session
session_manager = SessionManager(timeout_seconds=30)


@router.get("/read")
async def read_nfc_cards(
    request: Request,
    hardware: HardwareManager = Depends(get_hardware),
    story_manager: StoryManager = Depends(get_story_manager),
) -> EventSourceResponse:
    """Stream NFC card tap events via Server-Sent Events.

    Returns SSE stream with enriched events including card_type:
    {"uid": "04:A3:5B:C2:D4:30", "card_type": "story"}
    {"uid": "...", "card_type": "parameter", "category": "...", ...}
    {"uid": "...", "card_type": "go"}
    {"uid": "...", "card_type": "unknown"}
    """

    async def event_stream() -> AsyncIterator[dict]:
        """Generate SSE events for NFC card taps."""
        # Phase 33-05 D-01: reach the engine via the SAFE getattr pattern.
        # tests/test_api/test_nfc.py builds TestClient(app) WITHOUT a context
        # manager, so the lifespan never runs and app.state.led_animator is
        # never set; direct attribute access would raise AttributeError
        # (T-33-11). Every call below is None-guarded so a missing engine
        # degrades to no LED feedback rather than breaking the NFC SSE stream.
        animator = getattr(request.app.state, "led_animator", None)
        nfc_service = hardware._services.get("nfc")
        if not nfc_service:
            yield {
                "event": "error",
                "data": json.dumps({"error": "NFC service not available"}),
            }
            return

        queue: asyncio.Queue[str] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def card_callback(uid: str) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, uid)

        await nfc_service.start_polling(card_callback)

        try:
            while True:
                uid = await queue.get()

                card = story_manager.get_card(uid)

                if card is None:
                    yield {
                        "event": "card",
                        "data": json.dumps({"uid": uid, "card_type": "unknown"}),
                    }
                elif card["type"] == "story":
                    session_manager.clear()
                    # LED-13 / D-11: brief neutral/white confirmation flash
                    # (D-19 rate-limited inside the engine — a double-tap shows
                    # one flash). Driven through the engine, the sole writer.
                    if animator is not None:
                        animator.flash(255, 255, 255, ms=200)
                    yield {
                        "event": "card",
                        "data": json.dumps(
                            {"uid": uid, "card_type": "story"}
                        ),
                    }
                elif card["type"] == "parameter":
                    # SessionManager has side effects on each tap — call it
                    # exactly once and reuse its return value for the count.
                    params = session_manager.add_parameter(card)
                    n = len(params)
                    # LED-19 / D-20: drive Mode.PARAM with n_params from the
                    # session so each parameter tap lights one more pixel from
                    # index 0 in the neutral accumulation color. Mode.PARAM
                    # renders led_effects.param_fill(n_params=n). NOT PROGRESS
                    # / THINKING — parameter accumulation is its own mode.
                    if animator is not None:
                        animator.set_mode(Mode.PARAM, n_params=n)
                    yield {
                        "event": "card",
                        "data": json.dumps(
                            {
                                "uid": uid,
                                "card_type": "parameter",
                                "category": card.get("category", ""),
                                "value": card.get("value", ""),
                                "emoji": card.get("emoji", ""),
                                "label": card.get("label", ""),
                            }
                        ),
                    }
                elif card["type"] == "go":
                    params = session_manager.get_and_clear()
                    # LED-14 / D-11: distinct longer celebratory green flash
                    # (~400 ms) for the "start!" moment. Same rate-limited
                    # overlay slot as the tap flash. Driven through the engine.
                    if animator is not None:
                        animator.flash(0, 255, 0, ms=400)
                    yield {
                        "event": "card",
                        "data": json.dumps(
                            {
                                "uid": uid,
                                "card_type": "go",
                                "parameters": params,
                            }
                        ),
                    }
        finally:
            await nfc_service.stop_polling(card_callback)

    return SSEStarletteResponse(event_stream(), media_type="text/event-stream")


@router.get("/status")
async def get_nfc_status(
    hardware: HardwareManager = Depends(get_hardware),
) -> dict:
    """Get NFC service status."""
    nfc_service = hardware._services.get("nfc")
    if not nfc_service:
        return {
            "name": "nfc",
            "is_mock": True,
            "status": "not_connected",
            "error_message": "NFC service not registered",
        }

    return await nfc_service.get_status()
