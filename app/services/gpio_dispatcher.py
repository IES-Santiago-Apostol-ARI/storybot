"""GpioDispatcher — drains GPIO button events and routes them to handlers.

Sits between the inbound ``gpio_events`` queue (populated by gpio_handler.py's
edge callbacks, Phase 35) and the outbound ``kiosk_events`` queue (drained by
Phase 37's SSE). It owns the four button-name actions:

- **power** (BTN-01, D-03): delegate to ``system_control.poweroff()``.
- **interrupt** (BTN-02, D-05): ``audio_player.stop()`` + clear the PlaybackState
  snapshot + enqueue ``{"type": "interrupt"}`` onto kiosk_events.
- **animation** (BTN-05, D-11): one-shot ``LedAnimator.rainbow()``.
- **image**: print ``content/last-cover`` (the cover of the last finished
  story, kept fresh by the led/state and generate routes) on the Brother QL;
  drop-on-busy guard, rainbow ack / ``Mode.ERROR`` blink.

A per-button debounce-once guard (D-02/BTN-07) enforces "fires exactly once per
press" using ``settings.gpio_debounce_ms`` (50 ms — explicitly NOT
``gpio_bounce_ms`` = 200). The clock is injectable via ``now=`` so the conftest
fake_clock drives it deterministically.
"""

import asyncio
import json
import sys
import time
from typing import Any

from app.config import get_settings
from app.services import printer_handler, system_control
from app.services.led_animator import Mode


def _log(event: str, **fields: Any) -> None:
    """Structured stderr log (never raises)."""
    try:
        print(json.dumps({"event": event, **fields}), file=sys.stderr)
    except Exception:  # pragma: no cover — logging must never crash the loop
        pass


class GpioDispatcher:
    """Async GPIO event dispatcher with debounce and four button handlers.

    Args:
        gpio_events: Inbound queue of raw button name strings (e.g. "power").
        kiosk_events: Outbound queue where structured event dicts are enqueued
            for the kiosk UI / SSE consumers.
        audio_player: AudioPlayer for the interrupt handler, or None.
        led_animator: LedAnimator for rainbow ack / Mode.ERROR feedback, or None.
        printer: PrinterService for the image button, or None (error blink).
        playback_holder: object exposing a mutable ``.playback`` attribute that
            holds the current PlaybackState snapshot ``{story_id, params, title}``
            or None. In production this is ``app.state``; in unit tests it is a
            small stand-in. The dispatcher reads it live so it always sees the
            current story.
        now: monotonic clock callable (defaults to ``time.monotonic``), injected
            for deterministic debounce tests.
    """

    def __init__(
        self,
        gpio_events: asyncio.Queue,
        kiosk_events: asyncio.Queue,
        *,
        audio_player: Any = None,
        led_animator: Any = None,
        printer: Any = None,
        playback_holder: Any = None,
        now: Any = None,
    ) -> None:
        self._gpio_events = gpio_events
        self._kiosk_events = kiosk_events
        self._audio_player = audio_player
        self._led_animator = led_animator
        self._printer = printer
        self._playback_holder = playback_holder
        self._now = now or time.monotonic

        # Per-button debounce state: last accepted timestamp per button name.
        self._last_fired: dict[str, float] = {}

        # Drop-on-busy guard: a double press must not print twice.
        self._image_busy = False

    # ------------------------------------------------------------------ #
    # Debounce
    # ------------------------------------------------------------------ #
    def _is_debounced(self, button: str) -> bool:
        """True if *button* fired within ``gpio_debounce_ms`` (drop it)."""
        last = self._last_fired.get(button)
        if last is None:
            return False
        return (self._now() - last) * 1000 < get_settings().gpio_debounce_ms

    # ------------------------------------------------------------------ #
    # Dispatch
    # ------------------------------------------------------------------ #
    async def _handle_event(self, button: str) -> None:
        """Process one GPIO button event: debounce, then route to its handler."""
        # D-02/BTN-07: debounce-once guard
        if self._is_debounced(button):
            return
        self._last_fired[button] = self._now()

        if button == "power":
            await self._handle_power()
        elif button == "interrupt":
            await self._handle_interrupt()
        elif button == "animation":
            self._handle_animation()
        elif button == "image":
            self._handle_image()

    async def _handle_power(self) -> None:
        """BTN-01/D-03: delegate to the shared poweroff helper (monkeypatch seam)."""
        await system_control.poweroff()

    async def _handle_interrupt(self) -> None:
        """BTN-02/D-05: stop audio, clear PlaybackState, enqueue interrupt event."""
        if self._audio_player is not None:
            await self._audio_player.stop()
        if self._playback_holder is not None:
            # The interrupted story's cover becomes the image button's
            # last-cover (no need to listen to the whole story to print it).
            snap = self._playback_holder.playback
            if snap and snap.get("story_id"):
                await asyncio.to_thread(
                    printer_handler.save_story_cover,
                    snap["story_id"],
                    snap.get("cover_image"),
                )
            self._playback_holder.playback = None
        self._kiosk_events.put_nowait({"type": "interrupt"})

    def _handle_animation(self) -> None:
        """BTN-05/D-11: one-shot rainbow effect."""
        if self._led_animator is not None:
            self._led_animator.rainbow()

    # ------------------------------------------------------------------ #
    # Image button: print the last finished story's cover
    # ------------------------------------------------------------------ #
    def _error_blink(self) -> None:
        """D-09/D-10: short error blink via the engine (sole writer)."""
        if self._led_animator is not None:
            self._led_animator.set_mode(Mode.ERROR)

    def _handle_image(self) -> None:
        """Print content/last-cover in a background task (buttons stay instant).

        No printer or no cover saved yet → error blink. Re-presses while a
        print is in flight are dropped.
        """
        if self._image_busy:
            return
        if self._printer is None or not printer_handler.LAST_COVER.is_file():
            self._error_blink()
            return
        self._image_busy = True
        asyncio.create_task(self._print_last_cover())

    async def _print_last_cover(self) -> None:
        """Rainbow ack on success; error blink on failure (e.g. printer off —
        the job is dropped, never queued). Busy guard reset in ``finally``."""
        try:
            await self._printer.print_sticker(printer_handler.LAST_COVER)
            if self._led_animator is not None:
                self._led_animator.rainbow()
        except Exception as e:
            _log("cover_print_error", reason=type(e).__name__)
            self._error_blink()
        finally:
            self._image_busy = False

    # ------------------------------------------------------------------ #
    # Run loop
    # ------------------------------------------------------------------ #
    async def run(self) -> None:
        """Background task — drain gpio_events and dispatch, resiliently.

        Each event is wrapped in try/except so one handler exception cannot kill
        the loop (T-36-02). Cancelled cleanly on shutdown from the lifespan.
        """
        try:
            while True:
                button = await self._gpio_events.get()
                try:
                    await self._handle_event(button)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    _log(
                        "dispatcher_handler_error",
                        button=button,
                        reason=type(e).__name__,
                    )
        except asyncio.CancelledError:
            raise
