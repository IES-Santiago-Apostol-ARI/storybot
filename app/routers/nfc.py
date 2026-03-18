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

Thread Safety:
    - NFC polling runs in daemon thread (from Phase 0)
    - Server remains responsive during polling
    - SSE disconnection stops polling for that client
    - StoryManager uses threading.Lock for NFC mapping updates
"""

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import EventSourceResponse
from sse_starlette import EventSourceResponse as SSEStarletteResponse

from app.dependencies import get_hardware
from app.services.hardware_manager import HardwareManager

router = APIRouter(prefix="/api/nfc", tags=["nfc"])


@router.get("/read")
async def read_nfc_cards(
    hardware: HardwareManager = Depends(get_hardware),
) -> EventSourceResponse:
    """Stream NFC card tap events via Server-Sent Events.

    Returns SSE stream with events like:
    {"uid": "04:A3:5B:C2:D4:30"}
    """

    async def event_stream() -> AsyncIterator[dict]:
        """Generate SSE events for NFC card taps."""
        # Get NFC service from hardware manager
        nfc_service = hardware._services.get("nfc")
        if not nfc_service:
            yield {
                "event": "error",
                "data": json.dumps({"error": "NFC service not available"}),
            }
            return

        # Create queue for card events
        queue: asyncio.Queue[str] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def card_callback(uid: str) -> None:
            """Callback when card tapped (called from background thread)."""
            loop.call_soon_threadsafe(queue.put_nowait, uid)

        # Start polling
        await nfc_service.start_polling(card_callback)

        try:
            while True:
                # Wait for card tap
                uid = await queue.get()
                yield {
                    "event": "card",
                    "data": json.dumps({"uid": uid}),
                }
        finally:
            # Unregister this client's callback; stops polling if last subscriber
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
