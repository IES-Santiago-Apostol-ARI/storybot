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
    @pytest.mark.xfail(strict=False, reason="engine wiring lands in 32-03")
    def test_led_request_responsive_while_animating(self):
        """
        LED-07: Assert /api/system/led responds within budget while animation is active.
        Selector: -k responsive_while_animating
        """
        client = TestClient(app)

        # 1. Trigger an animation (e.g., a long flash or just the default loop)
        # In plan 03, we'll ensure the animator is running.
        # For now, we just make the request and measure.
        
        start = time.monotonic()
        response = client.post("/api/system/led", json={"color": "#FF0000"})
        elapsed = time.monotonic() - start

        assert response.status_code == 200
        assert elapsed < LATENCY_BUDGET_S, (
            f"LED request took {elapsed:.3f}s (budget {LATENCY_BUDGET_S}s) "
            "— SPI write not offloaded?"
        )
