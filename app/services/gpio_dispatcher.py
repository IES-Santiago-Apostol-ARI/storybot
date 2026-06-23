"""GpioDispatcher — drains GPIO button events and routes them to handlers.

Sits between the inbound ``gpio_events`` queue (populated by gpio_handler.py's
edge callbacks, Phase 35) and the outbound ``kiosk_events`` queue (drained by
Phase 37's SSE). It owns the four button-name actions:

- **power** (BTN-01, D-03): delegate to ``system_control.poweroff()``.
- **interrupt** (BTN-02, D-05): ``audio_player.stop()`` + clear the PlaybackState
  snapshot + enqueue ``{"type": "interrupt"}`` onto kiosk_events.
- **animation** (BTN-05, D-11): one-shot ``LedAnimator.rainbow()``.
- **image** (BTN-03/04, D-08/09/10): background cover generation via
  ``swap_orchestrator``, drop-on-busy guard, rainbow ack / ``Mode.ERROR`` blink,
  and the nothing-playing / no-params edge cases.

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

from app.config import ConfigManager
from app.services import cover_prompt_builder, system_control
from app.services.led_animator import Mode

settings = ConfigManager().load()


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
        swap_orchestrator: SwapOrchestrator for cover generation, or None on a
            non-AI profile (the image handler degrades to Mode.ERROR).
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
        swap_orchestrator: Any = None,
        playback_holder: Any = None,
        now: Any = None,
    ) -> None:
        self._gpio_events = gpio_events
        self._kiosk_events = kiosk_events
        self._audio_player = audio_player
        self._led_animator = led_animator
        self._swap_orchestrator = swap_orchestrator
        self._playback_holder = playback_holder
        self._now = now or time.monotonic

        # Per-button debounce state: last accepted timestamp per button name.
        self._last_fired: dict[str, float] = {}

        # Drop-on-busy in-flight guard for the image handler (D-08).
        self._image_busy = False

    # ------------------------------------------------------------------ #
    # Playback snapshot
    # ------------------------------------------------------------------ #
    def _playback(self) -> dict | None:
        """Read the current PlaybackState snapshot from the holder (live)."""
        return getattr(self._playback_holder, "playback", None)

    # ------------------------------------------------------------------ #
    # Debounce
    # ------------------------------------------------------------------ #
    def _is_debounced(self, button: str) -> bool:
        """True if *button* fired within ``gpio_debounce_ms`` (drop it)."""
        last = self._last_fired.get(button)
        if last is None:
            return False
        return (self._now() - last) * 1000 < settings.gpio_debounce_ms

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
            self._playback_holder.playback = None
        self._kiosk_events.put_nowait({"type": "interrupt"})

    def _handle_animation(self) -> None:
        """BTN-05/D-11: one-shot rainbow effect."""
        if self._led_animator is not None:
            self._led_animator.rainbow()

    # ------------------------------------------------------------------ #
    # Image button (BTN-03/04)
    # ------------------------------------------------------------------ #
    def _error_blink(self) -> None:
        """D-09/D-10: short error blink via the engine (sole writer)."""
        if self._led_animator is not None:
            self._led_animator.set_mode(Mode.ERROR)

    def _handle_image(self) -> None:
        """BTN-03/04: launch background cover generation for the playing story.

        D-10 nothing-playing → safe no-op + Mode.ERROR blink. Drop-on-busy
        (D-08): re-presses while a generation is in flight are dropped. A None
        orchestrator (non-AI profile) degrades to Mode.ERROR. Generation runs in
        a background asyncio task so power/interrupt/animation stay instant.
        """
        snapshot = self._playback()

        # D-10/BTN-04: nothing playing → safe no-op + error blink.
        if not snapshot:
            self._error_blink()
            return

        # D-08: drop re-presses while a generation is already in flight.
        if self._image_busy:
            return

        # Non-AI profile: no orchestrator → error blink, never AttributeError.
        if self._swap_orchestrator is None:
            self._error_blink()
            return

        # D-10: use the snapshot params, else synthesize a title-based fallback
        # so the image button always tries to produce something while playing.
        params = snapshot.get("params") or []
        if not params:
            title = snapshot.get("title", "") or ""
            params = [{"category": "personaje", "value": title}]

        positive, negative = cover_prompt_builder.build(params)
        story_id = snapshot.get("story_id")

        self._image_busy = True
        asyncio.create_task(self._generate_cover(story_id, positive, negative))

    async def _generate_cover(
        self, story_id: str, positive: str, negative: str
    ) -> None:
        """Background task: run the orchestrator, then ack or error-blink.

        On success enqueues ``{"type": "image", "url": ...}`` (URL derived from
        the orchestrator's actual preview filename) and fires ``rainbow()`` as
        the press ack (D-09). On busy/failure/exception drives ``Mode.ERROR``.
        The in-flight guard is reset in ``finally`` regardless of outcome.
        """
        try:
            seed = hash(story_id) & 0xFFFFFFFF
            preview_path, _print_path, _gen_seconds = (
                await self._swap_orchestrator.generate_cover_for_story(
                    story_id, positive, negative, seed
                )
            )

            # Busy-lock or failure → (None, None, None).
            if preview_path is None:
                self._error_blink()
                return

            # Derive the URL from the actual output filename (avoids a silent
            # 404 if the worker's basename ever changes).
            url = f"/static/generated/{story_id}/{preview_path.name}"
            self._kiosk_events.put_nowait({"type": "image", "url": url})
            if self._led_animator is not None:
                self._led_animator.rainbow()

        except Exception as e:
            _log(
                "cover_generation_error",
                story_id=story_id,
                reason=type(e).__name__,
            )
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
