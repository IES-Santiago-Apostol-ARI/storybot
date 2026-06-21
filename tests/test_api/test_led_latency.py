"""LED API responsiveness regression test.

Ensures that the /api/system/led endpoint remains responsive (< 0.5s)
even while the background animation loop is active. This verifies
that SPI writes are properly offloaded to threads and not blocking
the event loop.
"""

import time
import pytest
from fastapi.testclient import TestClient
from app.main import app

# A1 measure-once budget: 0.5s for a single /led round-trip while animating
LATENCY_BUDGET_S = 0.5

class TestLEDLatency:
    def test_led_request_responsive_while_animating(self):
        """
        LED-07: Assert /api/system/led responds within budget while animation is active.
        Selector: -k responsive_while_animating

        Entering the TestClient context manager runs the real lifespan, which
        starts the 30 FPS LedAnimator loop over MockLEDService (D-12). The
        round-trip is measured while that loop is live — passing at all proves
        the blocking SPI write is offloaded via asyncio.to_thread, not blocking
        the event loop that serves the request (LED-07).
        """
        with TestClient(app) as client:
            start = time.monotonic()
            response = client.post("/api/system/led", json={"color": "#FF0000"})
            elapsed = time.monotonic() - start

        assert response.status_code == 200
        assert elapsed < LATENCY_BUDGET_S, (
            f"LED request took {elapsed:.3f}s (budget {LATENCY_BUDGET_S}s) "
            "— SPI write not offloaded?"
        )

    def test_state_request_responsive_while_animating(self):
        """
        LED-07: Assert /api/system/led/state responds within budget while
        an animated (non-static) effect is ticking.

        Drives the engine into an animated mode (playback with breathing),
        then measures a /led/state round-trip stays under budget — proving
        SPI writes stay offloaded even while a non-solid effect renders.
        """
        with TestClient(app) as client:
            # Drive engine into animated mode
            client.post(
                "/api/system/led/state",
                json={"state": "playback", "story_id": "test-story"},
            )
            start = time.monotonic()
            response = client.post(
                "/api/system/led/state",
                json={"state": "idle"},
            )
            elapsed = time.monotonic() - start

        assert response.status_code == 200
        assert elapsed < LATENCY_BUDGET_S, (
            f"/led/state request took {elapsed:.3f}s (budget {LATENCY_BUDGET_S}s) "
            "— SPI write not offloaded during animated effect?"
        )
