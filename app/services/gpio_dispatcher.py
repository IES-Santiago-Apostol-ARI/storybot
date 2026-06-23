"""GpioDispatcher — consumes GPIO events and routes them to handlers.

Sits between the raw gpio_events queue (populated by gpio_handler.py's edge
callbacks) and the kiosk_events queue consumed by the UI. Provides:

- Debounce guard (BTN-02): blocks rapid re-trigger of the same button within
  ``settings.gpio_debounce_ms`` milliseconds.
- LED feedback (BTN-05): triggers a rainbow animation on power button press.
- Kiosk event dispatch (BTN-07): puts structured events onto kiosk_events
  without blocking.
"""

import asyncio
import time
from typing import Any

from app.config import ConfigManager

settings = ConfigManager().load()


class GpioDispatcher:
    """Async GPIO event dispatcher with debounce and kiosk routing.

    Consumes button names from ``gpio_events`` (an asyncio.Queue populated by
    the GPIO handler's edge callbacks), applies a per-button debounce guard,
    triggers LED feedback for power button presses, and routes structured
    events onto ``kiosk_events`` for the UI to consume.

    Args:
        gpio_events: Queue of raw button name strings (e.g., "power").
        kiosk_events: Queue where structured event dicts are enqueued for
            the kiosk UI / SSE consumers.
        led_animator: LedAnimator instance for LED feedback, or None.
    """

    def __init__(
        self,
        gpio_events: asyncio.Queue,
        kiosk_events: asyncio.Queue,
        led_animator: Any = None,
    ) -> None:
        self._gpio_events = gpio_events
        self._kiosk_events = kiosk_events
        self._led_animator = led_animator

        # Per-button debounce state: last accepted timestamp per button name.
        self._last_dispatched: dict[str, float] = {}

    def _is_debounced(self, button: str) -> bool:
        """Check if an event for *button* is within the debounce window.

        Returns True if the event should be dropped (debounced), False if it
        should be accepted.
        """
        last = self._last_dispatched.get(button, 0.0)
        elapsed_ms = (time.monotonic() - last) * 1000
        return elapsed_ms < settings.gpio_debounce_ms

    async def _handle_event(self, button: str) -> None:
        """Process a single GPIO button event.

        Applies debounce guard, triggers LED feedback for power button, and
        enqueues the structured event onto kiosk_events.
        """
        # BTN-02: debounce guard
        if self._is_debounced(button):
            return

        # Record acceptance time
        self._last_dispatched[button] = time.monotonic()

        # BTN-05: LED feedback on power button press
        if button == "power" and self._led_animator is not None:
            self._led_animator.rainbow()

        # BTN-07: dispatch to kiosk event queue (non-blocking)
        event = {
            "button": button,
            "timestamp": time.monotonic(),
        }
        self._kiosk_events.put_nowait(event)

    async def run(self) -> None:
        """Background task — consume gpio_events and dispatch to handlers.

        Runs until cancelled. Catches CancelledError and re-raises for clean
        shutdown from the lifespan.
        """
        try:
            while True:
                button = await self._gpio_events.get()
                await self._handle_event(button)
        except asyncio.CancelledError:
            raise
