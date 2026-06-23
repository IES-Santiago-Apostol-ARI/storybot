"""GpioDispatcher — consumes GPIO events and routes them to handlers.

Sits between the raw gpio_events queue (populated by gpio_handler.py's edge
callbacks) and the kiosk_events queue consumed by the UI. Provides:

- Debounce guard (BTN-02): blocks rapid re-trigger of the same button within
  ``settings.gpio_debounce_ms`` milliseconds.
- LED feedback (BTN-05): triggers a rainbow animation on power button press.
- Kiosk event dispatch (BTN-07): puts structured events onto kiosk_events
  without blocking.
- Image button handler (BTN-03, BTN-04): triggers background cover generation
  for the currently playing story via swap_orchestrator, with drop-on-busy
  guard and D-10 edge-case handling.
"""

import asyncio
import random
import time
from typing import Any

from app.config import ConfigManager

settings = ConfigManager().load()


class GpioDispatcher:
    """Async GPIO event dispatcher with debounce and kiosk routing.

    Consumes button names from ``gpio_events`` (an asyncio.Queue populated by
    the GPIO handler's edge callbacks), applies a per-button debounce guard,
    triggers LED feedback for power button presses, routes structured events
    onto ``kiosk_events``, and handles image button presses by triggering
    background cover generation via swap_orchestrator.

    Args:
        gpio_events: Queue of raw button name strings (e.g., "power").
        kiosk_events: Queue where structured event dicts are enqueued for
            the kiosk UI / SSE consumers.
        led_animator: LedAnimator instance for LED feedback, or None.
        swap_orchestrator: SwapOrchestrator instance for cover generation,
            or None when unavailable.
    """

    def __init__(
        self,
        gpio_events: asyncio.Queue,
        kiosk_events: asyncio.Queue,
        led_animator: Any = None,
        swap_orchestrator: Any = None,
    ) -> None:
        self._gpio_events = gpio_events
        self._kiosk_events = kiosk_events
        self._led_animator = led_animator
        self._swap_orchestrator = swap_orchestrator

        # Per-button debounce state: last accepted timestamp per button name.
        self._last_dispatched: dict[str, float] = {}

        # Currently playing story ID — set by the playback lifecycle (e.g.,
        # via /api/system/led/state when state=playback). Used by the image
        # button handler to know which story to generate a cover for.
        self.current_story_id: str | None = None

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

        Applies debounce guard, triggers LED feedback for power button, handles
        image button cover generation (BTN-03/04), and enqueues the structured
        event onto kiosk_events.
        """
        # BTN-02: debounce guard
        if self._is_debounced(button):
            return

        # Record acceptance time
        self._last_dispatched[button] = time.monotonic()

        # BTN-05: LED feedback on power button press
        if button == "power" and self._led_animator is not None:
            self._led_animator.rainbow()

        # BTN-03/04: Image button — trigger background cover generation
        if button == "image":
            await self._handle_image_button()

        # BTN-07: dispatch to kiosk event queue (non-blocking)
        event = {
            "button": button,
            "timestamp": time.monotonic(),
        }
        self._kiosk_events.put_nowait(event)

    async def _handle_image_button(self) -> None:
        """Handle image button press — trigger background cover generation.

        BTN-03: If a story is currently playing, call swap_orchestrator to
        generate a cover. Uses cover_prompt_builder for a title-based fallback
        prompt (empty params).

        BTN-04: Generation runs in the background via asyncio.create_task so
        the dispatcher loop is never blocked.

        D-10 edge cases:
        - current_story_id is None → skip generation, no crash.
        - swap_orchestrator is None → skip generation, no crash.
        - generate_cover_for_story raises → catch and log, no crash.
        - Returns (None, None, None) on busy → drop-on-busy guard, no retry.
        """
        # D-10: No story playing — nothing to generate a cover for
        if self.current_story_id is None:
            return

        # D-10: Swap orchestrator unavailable — graceful degradation
        if self._swap_orchestrator is None:
            return

        # Build fallback prompt (empty params → style preamble only)
        from app.services.cover_prompt_builder import build as build_cover_prompt

        positive, negative = build_cover_prompt([])

        # BTN-04: Run in background — never block the dispatcher loop
        asyncio.create_task(
            self._generate_cover(self.current_story_id, positive, negative)
        )

    async def _generate_cover(
        self, story_id: str, positive: str, negative: str
    ) -> None:
        """Background task: call swap_orchestrator to generate a cover.

        Drop-on-busy guard: if the orchestrator returns (None, None, None),
        the event is silently dropped — no retry, no block.

        Args:
            story_id: The currently playing story ID.
            positive: Positive prompt for the cover generator.
            negative: Negative prompt for the cover generator.
        """
        try:
            seed = random.randint(0, 2**31 - 1)
            (
                preview_path,
                print_path,
                gen_seconds,
            ) = await self._swap_orchestrator.generate_cover_for_story(
                story_id, positive, negative, seed
            )

            if preview_path is None:
                # Busy or failed — drop silently (BTN-04)
                return

            # Enqueue cover result onto kiosk events for the UI to consume
            self._kiosk_events.put_nowait(
                {
                    "button": "image",
                    "event": "cover_generated",
                    "story_id": story_id,
                    "preview_url": f"/static/generated/{story_id}/cover-preview.png",
                    "print_path": str(print_path),
                    "gen_seconds": gen_seconds,
                }
            )

        except Exception:  # pragma: no cover — D-10 defensive; logged via stderr
            import json
            import sys

            print(
                json.dumps(
                    {
                        "event": "cover_generation_error",
                        "story_id": story_id,
                        "reason": "exception_in_dispatcher",
                    }
                ),
                file=sys.stderr,
            )

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
