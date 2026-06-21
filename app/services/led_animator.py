"""LedAnimator async render engine — the sole writer to the WS2812B strip.

Implements the Phase 32 async animation engine (LED-06, LED-08). This engine
owns a fixed ~30 FPS drift-free render loop (D-05) that is the only code path
which writes encoded frames to the strip. The blocking SPI write is offloaded
via ``asyncio.to_thread`` so the single event loop streaming TTS/NFC SSE stays
responsive (D-01, LED-07 mechanism). RGB stays at the engine boundary; GRB /
gamma / cap remain below it in ``encode_ws2812`` (D-03).

Two-slot preempt/restore model (D-07 / D-08 / D-10):
- One persistent **base** slot (off / solid / future idle).
- One optional **transient overlay** (latest-wins, no queue).
- ``_active_color()`` returns the overlay while ``now() < _overlay_until`` and
  auto-clears it on the next tick after expiry, resuming the base.
- ``set_base`` updates the base slot *silently underneath* an active flash; the
  flash keeps playing and restores to the **new** base when it ends (D-10).

Dirty-check (D-06): the SPI write fires only when the newly-encoded frame
differs by value (``!=`` on ``bytes``, never ``is`` — Pitfall 5) from the last
written frame. Holding a solid color costs no bus traffic.

No child-safety clamps (<=3 flashes/sec, gamma) are enforced in this phase
(D-04, deferred to Phase 33); the engine relies on the existing ~0.30
brightness cap applied below the boundary in ``encode_ws2812``.

Engine driver-agnosticism (A3): ``_write(encoded)`` receives the already-encoded
immutable ``bytes`` frame. On the real driver it calls into the
``SpiWriter.write`` path; on the ``MockLEDService`` it is an explicit no-op —
it receives encoded bytes (not RGB ints), so it does NOT call the mock's
``set_color``. The engine tracks its own ``_base`` / ``_active_color`` for
status and ``_last_written`` for the dirty-check.
"""

import asyncio
import json
import sys
import time

from app.config import ConfigManager
from app.services.led_spi import encode_ws2812

settings = ConfigManager().load()


def _log_event(event: str, **kwargs: object) -> None:
    """Structured JSON log to stderr (mirrors led_controller._log_event)."""
    print(json.dumps({"event": event, **kwargs}), file=sys.stderr)


class LedAnimator:
    """Async render engine — sole writer to the WS2812B strip.

    Public API (RGB-in, latest-wins, attribute writes):
        - ``set_base(r, g, b)``: clamp + assign the persistent base slot.
        - ``off()``: set the base to black.
        - ``flash(r, g, b, ms)``: clamp + assign a transient overlay that
          preempts the base for ``ms`` milliseconds (latest-wins, no queue).
        - ``tick_once()``: per-tick render body — compute the active color,
          build + encode the frame on the loop, dirty-check, and offload only
          the blocking write via ``asyncio.to_thread``.
        - ``run()``: drift-free ~30 FPS loop that wraps ``tick_once`` in
          ``try/except Exception`` so the loop never dies (Pitfall 4); lets
          ``CancelledError`` propagate for clean shutdown (D-02).
        - ``get_color()``: status read — returns the active rendered color
          (overlay-while-active else base). See D-11 / Open Question 1.
    """

    # D-05: fixed ~30 FPS always-on render loop (~33 ms tick).
    _period: float = 1.0 / 30.0

    def __init__(self, led_service, now=None) -> None:
        """Initialize the animator.

        Args:
            led_service: The probed LED driver (RealLEDService on Jetson,
                MockLEDService on x86/CI). Used by the real-driver write path;
                its public surface is NOT modified (Surgical Changes).
            now: Optional monotonic clock callable (default ``time.monotonic``)
                injected for deterministic preempt/restore tests.
        """
        self._led_service = led_service
        self._now = now or time.monotonic
        # Two-slot state (D-07 / D-10).
        self._base: tuple[int, int, int] = (0, 0, 0)
        self._overlay: tuple[int, int, int] | None = None
        self._overlay_until: float = 0.0
        # D-06 dirty-check cache (value-equality on encoded bytes).
        self._last_written: bytes | None = None

    # --- public API -----------------------------------------------------

    async def set_base(self, r: int, g: int, b: int) -> None:
        """Clamp + assign the persistent base slot.

        D-10: silently updates the base UNDER any active flash; the flash keeps
        playing and restores to this new base when it expires.
        """
        self._base = (self._clamp(r), self._clamp(g), self._clamp(b))

    async def off(self) -> None:
        """Set the base to black."""
        self._base = (0, 0, 0)

    def flash(self, r: int, g: int, b: int, ms: int) -> None:
        """Clamp + assign a transient overlay for ``ms`` milliseconds.

        D-09 / D-10: replaces any active overlay immediately (latest-wins, no
        queue); preempts the base on the next tick (D-08) and auto-restores to
        the base when it expires.
        """
        self._overlay = (self._clamp(r), self._clamp(g), self._clamp(b))
        self._overlay_until = self._now() + ms / 1000.0

    def set_driver(self, led_service) -> None:
        """Re-point the engine at a freshly-probed driver (CR-02).

        ``hardware.rescan()`` -> ``detect_hardware`` replaces the registered
        ``"led"`` service with a NEW instance. Without this the engine would keep
        writing to the orphaned old driver while a new ``RealLEDService`` could
        contend for the same SPI bus (split-brain / dual owners). The dirty-check
        cache is cleared so the next tick re-writes the current frame to the new
        driver instead of being skipped by value-equality against the old one.
        """
        self._led_service = led_service
        self._last_written = None

    def get_color(self) -> tuple[int, int, int]:
        """Status read: return the active rendered color.

        D-11: ``/status`` reports the currently-rendered color so observers see
        the live state (base or active overlay). During an active flash this is
        the overlay color; otherwise it is the persistent base.
        """
        return self._active_color()

    # --- per-tick render body + loop ------------------------------------

    async def tick_once(self) -> None:
        """Per-tick render body.

        Compute the active color (overlay-while-active else base), build the
        solid frame, encode it ON the event loop, dirty-check, and offload ONLY
        the blocking driver write via ``asyncio.to_thread`` (D-01, LED-07).
        """
        color = self._active_color()
        frame = [color] * settings.led_count
        # Encode on the loop (pure CPU, microseconds for 21 px).
        encoded = encode_ws2812(
            frame,
            count=settings.led_count,
            cap=settings.led_max_brightness,
            gamma=settings.led_gamma,
            order=settings.led_color_order,
            speed_hz=settings.led_spi_speed_hz,
        )
        # D-06 dirty-check: value equality, never ``is`` (Pitfall 5).
        if encoded != self._last_written:
            await asyncio.to_thread(self._write, encoded)
            self._last_written = encoded

    async def run(self) -> None:
        """Drift-free ~30 FPS render loop (RESEARCH Pattern 1).

        Mirrors ``bt_monitor.run()`` shape: body wrapped in ``try/except
        Exception`` so the loop never dies (Pitfall 4); ``CancelledError``
        (``BaseException`` in 3.10) propagates for clean shutdown (D-02).

        The next wake time is computed against ``loop.time()`` (monotonic) and
        accumulated by ``_period`` — NOT a bare ``asyncio.sleep(1/30)`` — so the
        average period stays exact under per-tick compute load.
        """
        loop = asyncio.get_running_loop()
        next_t = loop.time()
        try:
            while True:
                try:
                    await self.tick_once()
                except Exception as e:
                    # Pitfall 4: one bad frame cannot kill the sole writer.
                    _log_event("led_animator_loop_error", reason=type(e).__name__)
                next_t += self._period
                delay = next_t - loop.time()
                if delay < 0:
                    # Fell behind: resync, don't spiral.
                    next_t = loop.time()
                    delay = 0
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            # D-02 shutdown path: let CancelledError propagate so the lifespan
            # gather(return_exceptions=True) absorbs it cleanly.
            raise

    # --- internals ------------------------------------------------------

    def _active_color(self) -> tuple[int, int, int]:
        """Overlay-while-active else base; auto-clears expired overlay.

        D-07 / D-08: overlay wins until ``_overlay_until``; once expired the
        overlay is cleared on this call so the base resumes on the next tick.
        """
        if self._overlay is not None:
            if self._now() < self._overlay_until:
                return self._overlay
            # Auto-restore: clear the expired overlay.
            self._overlay = None
        return self._base

    def _write(self, encoded: bytes) -> None:
        """Sync driver write — the sole SPI-write seam.

        A3: receives the already-encoded immutable ``bytes`` frame. On the real
        driver it calls into the ``SpiWriter.write`` path; on the
        ``MockLEDService`` it is an explicit no-op (it does NOT call the mock's
        ``set_color`` — that takes RGB ints, while this receives encoded bytes).
        The engine tracks its own ``_base`` / ``_active_color`` for status and
        ``_last_written`` for the dirty-check, so the mock write records nothing.
        """
        writer = getattr(self._led_service, "_writer", None)
        if writer is not None:
            # RealLEDService path: blocking spidev writebytes2.
            writer.write(encoded)
        # MockLEDService has no _writer -> explicit no-op (A3).

    @staticmethod
    def _clamp(channel: int) -> int:
        """Clamp a color channel to 0-255 (mirrors MockLEDService.set_color)."""
        return max(0, min(255, channel))
