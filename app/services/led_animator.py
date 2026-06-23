"""LedAnimator async render engine — the sole writer to the WS2812B strip.

Implements the Phase 32 async animation engine (LED-06, LED-08) and the Phase 33
behavior layer (mode/priority arbitration D-13, per-pixel framebuffer render,
<=3 flash/sec rate-limit gate D-19, gamma-correct cross-fades D-17, error
auto-fade lifecycle D-15/D-16, boot sweep D-10, idle-only health beacon D-14).

The engine owns a fixed ~30 FPS drift-free render loop (D-05) that is the only
code path which writes encoded frames to the strip. The blocking SPI write is
offloaded via ``asyncio.to_thread`` so the single event loop streaming TTS/NFC
SSE stays responsive (D-01, LED-07 mechanism). RGB stays at the engine boundary;
GRB / gamma / cap remain below it in ``encode_ws2812`` (D-03).

Two-slot preempt/restore model (D-07 / D-08 / D-10):
- One persistent **base** slot rendered by the current ``Mode`` (Phase 33 D-13).
- One optional **transient overlay** (latest-wins, no queue); flashes are routed
  through a <=3/sec rate-limit gate (D-19, LED-23) at the top of ``flash``.
- ``_active_color()`` returns the overlay while ``now() < _overlay_until`` and
  auto-clears it on the next tick after expiry, resuming the base.
- ``set_base`` updates the base slot *silently underneath* an active flash; the
  flash keeps playing and restores to the **new** base when it ends (D-10).

Dirty-check (D-06): the SPI write fires only when the newly-encoded frame
differs by value (``!=`` on ``bytes``, never ``is`` — Pitfall 5) from the last
written frame. Holding a solid color costs no bus traffic.

Child-safety clamps enforced in this engine (Phase 33):
- <=3 flashes/sec rate-limit gate inside ``flash`` (LED-23 / D-19), using the
  injected clock (never ``time.monotonic()`` directly — Pitfall 4).
- Brightness cap (~0.30) and gamma LUT remain single-pointed below the boundary
  in ``encode_ws2812`` (CF-1/CF-2 / LED-24 / LED-25) — effects and cross-fades
  emit plain RGB above the boundary so they cannot double-gamma/double-cap
  (Pitfall 1).

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
from collections.abc import Callable
from enum import IntEnum

from app.config import ConfigManager
from app.services import led_effects
from app.services.led_spi import encode_ws2812

settings = ConfigManager().load()


def _log_event(event: str, **kwargs: object) -> None:
    """Structured JSON log to stderr (mirrors led_controller._log_event)."""
    print(json.dumps({"event": event, **kwargs}), file=sys.stderr)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert a ``#RRGGBB`` config color to an (r, g, b) tuple."""
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


class Mode(IntEnum):
    """Priority-ordered base modes (D-13). Value == priority.

    IDLE < PARAM = THINKING = PROGRESS < PLAYBACK < ERROR.
    The engine holds exactly one active base mode at a time (form 1,
    single-active-mode per RESEARCH A1); error's auto-fade lifecycle (D-16)
    handles "settle back to idle." Pause is NOT a mode — it is the ``_paused``
    flag on PLAYBACK (D-12).
    """

    IDLE = 0
    PARAM = 1  # parameter accumulation (D-20 / LED-19), superseded by PLAYBACK
    THINKING = 1
    PROGRESS = 1
    PLAYBACK = 2
    ERROR = 3  # highest base priority — overrides everything (D-15)


# String state names accepted by set_mode (D-02 semantic states + internal).
_STATE_TO_MODE: dict[str, Mode | str] = {
    "idle": Mode.IDLE,
    "ended": Mode.IDLE,  # ended == fade-to-idle (D-12 / LED-12)
    "thinking": Mode.THINKING,
    "progress": Mode.PROGRESS,
    "param": Mode.PARAM,
    "playback": Mode.PLAYBACK,
    "error": Mode.ERROR,
    # pause/resume are handled as the _paused flag, not modes (D-12):
    "pause": "pause",
    "resume": "resume",
    "boot": "boot",  # one-shot boot sweep (D-10 / LED-18)
}


class LedAnimator:
    """Async render engine — sole writer to the WS2812B strip.

    Public API (RGB-in, latest-wins, attribute writes):
        - ``set_base(r, g, b)``: clamp + assign the persistent base slot.
        - ``off()``: set the base to black.
        - ``flash(r, g, b, ms)``: clamp + assign a rate-limited transient
          overlay that preempts the base for ``ms`` milliseconds (latest-wins,
          no queue). <=3 flashes/sec (LED-23).
        - ``flash_tap()`` / ``flash_go()``: confirmation flashes (D-11) riding
          the overlay slot through the same rate-limit gate.
        - ``set_mode(mode, **params)``: replace the base with a mode + render
          params; snapshots the prior base framebuffer to start a cross-fade.
        - ``set_health(down)``: record hardware-down status for the idle-only
          beacon (D-14).
        - ``pause()`` / ``resume()``: freeze / re-anchor the playback breath
          (D-12); pause is a flag, NOT a separate mode.
        - ``tick_once()``: per-tick render body — render the mode framebuffer
          (or solid overlay), encode, dirty-check, and offload only the
          blocking write via ``asyncio.to_thread``.
        - ``run()``: drift-free ~30 FPS loop.
        - ``get_color()``: status read — overlay-while-active else the
          representative base color (first pixel of the last base framebuffer).
    """

    # D-05: fixed ~30 FPS always-on render loop (~33 ms tick).
    _period: float = 1.0 / 30.0

    # D-19: <=3 flashes/sec rate limit (LED-23).
    _MIN_FLASH_INTERVAL_S: float = 1.0 / 3.0

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
        self._overlay_fn: Callable[[float, int], list[tuple[int, int, int]]] | None = None
        self._overlay_started_at: float = 0.0
        self._overlay_until: float = 0.0
        # D-06 dirty-check cache (value-equality on encoded bytes).
        self._last_written: bytes | None = None
        # Last representative base color (first pixel of the last base frame);
        # used by get_color() / _active_color() for status reads.
        self._last_base_color: tuple[int, int, int] = (0, 0, 0)

        # --- Phase 33 mode/priority layer (D-13) ----------------------------
        self._mode: Mode = Mode.IDLE
        self._mode_color: tuple[int, int, int] = (0, 0, 0)
        self._progress_i: int = 0
        self._progress_n: int = 1
        self._param_count: int = 0
        self._mode_started_at: float = self._now()
        # D-12 pause / resume continuity (flag on PLAYBACK, NOT a mode).
        self._paused: bool = False
        self._frozen_phase: float = 0.0
        self._phase0: float = 0.0  # single re-anchor point for the breath clock

        # --- Cross-fade (D-17 / LED-22) -------------------------------------
        self._fade_from: list[tuple[int, int, int]] | None = None
        self._fade_start: float = 0.0
        self._fade_duration: float = 0.0

        # --- D-19 rate-limit gate state ------------------------------------
        self._last_flash_at: float = float("-inf")

        # --- D-14 idle-only health beacon ----------------------------------
        self._health_down: bool = False

        # --- D-10 / LED-18 boot one-shot (engine-internal) -----------------
        # Inactive until armed by set_mode("boot") or the lifespan trigger.
        self._boot_started_at: float | None = None
        self._boot_done: bool = True  # nothing to render until armed

        # --- D-15 / D-16 error lifecycle -----------------------------------
        self._error_lifetime_s: float = (
            led_effects._ERROR_AMBER_DURATION + led_effects._ERROR_AMBER_FADE
        )

        # Precompute config RGB colors once (avoid re-parsing each tick).
        self._idle_rgb = _hex_to_rgb(settings.led_idle_color)
        self._error_rgb = _hex_to_rgb(settings.led_error_color)
        self._accum_rgb = _hex_to_rgb(settings.led_accum_color)
        self._boot_color = (0, 150, 255)  # distinct from idle amber
        self._thinking_color = (200, 200, 255)  # cool white, distinct from amber
        # Low-amber beacon accent (idle only, D-14).
        self._beacon_color = (90, 60, 0)

    # --- public API -----------------------------------------------------

    async def set_base(self, r: int, g: int, b: int) -> None:
        """Clamp + assign the persistent base slot.

        D-10: silently updates the base UNDER any active flash; the flash keeps
        playing and restores to this new base when it expires.

        Phase 33: the base is what IDLE mode renders. ``set_mode("idle")`` loads
        the configured idle glow into the base; a direct ``set_base`` overrides
        it (used by the Phase 32 contract tests and the existing ``/led`` route).
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

        D-19 / LED-23: <=3 flashes/sec rate-limit gate at the TOP of this
        method. A second flash requested less than ~333 ms after the previous
        accepted flash is DROPPED (queue-free per RESEARCH Pattern 9). MUST use
        the injected ``self._now``, never ``time.monotonic()`` directly
        (Pitfall 4) so tests drive it deterministically via ``_FakeClock``.
        """
        if self._now() - self._last_flash_at < self._MIN_FLASH_INTERVAL_S:
            return  # DROP — too soon since the last accepted flash (LED-23)
        self._last_flash_at = self._now()
        self._overlay = (self._clamp(r), self._clamp(g), self._clamp(b))
        self._overlay_until = self._now() + ms / 1000.0

    def flash_tap(self) -> None:
        """LED-13 / D-11: brief neutral/white confirmation flash (~200 ms)."""
        self.flash(255, 255, 255, ms=200)

    def flash_go(self) -> None:
        """LED-14 / D-11: distinct celebratory green flash (~400 ms)."""
        self.flash(0, 255, 0, ms=400)

    def rainbow(self, duration_ms: int = 1500) -> None:
        """One-shot rainbow hue cycle (ANIM-01/ANIM-02). Modeled on flash(): sets a
        transient overlay render-fn + expiry; auto-returns to the base mode."""
        self._overlay_fn = led_effects.rainbow
        self._overlay_started_at = self._now()
        self._overlay_until = self._now() + duration_ms / 1000.0

    def set_mode(
        self,
        mode,
        *,
        color: tuple[int, int, int] | None = None,
        i: int | None = None,
        n: int | None = None,
        n_params: int | None = None,
    ) -> None:
        """Replace the base with a mode + its render params (D-13).

        Accepts either a ``Mode`` enum value or a semantic state string
        (D-02: "idle" / "playback" / "pause" / "resume" / "thinking" /
        "progress" / "param" / "error" / "ended" / "boot"). Snapshots the
        current base framebuffer to start a cross-fade (D-17) BEFORE swapping
        the mode (Pitfall 5).

        Pause / resume are NOT mode changes — they are the ``_paused`` flag on
        PLAYBACK (D-12); "pause" / "resume" route to :meth:`pause` /
        :meth:`resume`. Any ``set_mode`` other than re-entering PLAYBACK clears
        ``_paused``.
        """
        if isinstance(mode, str):
            resolved = _STATE_TO_MODE.get(mode)
            if resolved == "pause":
                self.pause()
                return
            if resolved == "resume":
                self.resume()
                return
            if resolved == "boot":
                self._boot_started_at = self._now()
                self._boot_done = False
                return
            if resolved is None:
                return  # unknown state — no-op (route layer validates / 422s)
            mode = resolved

        now = self._now()
        # Pitfall 5: snapshot the from-frame BEFORE swapping the mode.
        self._fade_from = self._render_mode(now, settings.led_count)
        # Crossfade began one tick ago so the first post-change frame already
        # shows a small blend toward the destination (frames render "next").
        self._fade_start = now - self._period
        self._fade_duration = settings.led_crossfade_s

        self._mode = mode
        self._mode_started_at = now
        if color is not None:
            self._mode_color = color
        if i is not None:
            self._progress_i = i
        if n is not None:
            self._progress_n = max(1, n)
        if n_params is not None:
            self._param_count = n_params

        if mode == Mode.IDLE:
            # Load the configured idle glow into the base so IDLE renders it.
            self._base = self._idle_rgb
        if mode == Mode.PLAYBACK:
            # Re-anchor the breath clock and clear pause on (re-)entering.
            self._phase0 = now
            self._paused = False
            self._frozen_phase = 0.0
        else:
            self._paused = False

    def set_health(self, down: bool) -> None:
        """Record hardware-down status for the idle-only beacon (D-14 / LED-21).

        The beacon itself renders ONLY when the resolved mode is IDLE; this just
        feeds the flag — the suppression lives in the engine.
        """
        self._health_down = down

    def pause(self) -> None:
        """D-12 / LED-11: freeze the breath into a steady-dim hold.

        AUTHORITATIVE mechanism: pause is a ``_paused`` flag on the existing
        PLAYBACK mode, NOT a separate pause mode. Stores the current breath
        phase so :meth:`resume` can re-anchor the clock for continuity.
        """
        if self._mode != Mode.PLAYBACK:
            return
        self._paused = True
        period = settings.led_breathe_period_s
        self._frozen_phase = (self._now() - self._phase0) % period
        # Freeze the frame: clear any in-progress cross-fade so the held frame
        # is the pure breathing-at-frozen-phase and stays constant across ticks
        # (the cross-fade alpha would otherwise keep advancing with time).
        self._fade_from = None

    def resume(self) -> None:
        """D-12 / LED-11: resume the breath, re-anchoring the phase clock.

        ``_phase0 = now - _frozen_phase`` keeps the breath continuous from where
        it froze (no hard jump). ``_phase0`` is the single re-anchor point.
        """
        if self._mode != Mode.PLAYBACK:
            return
        self._paused = False
        self._phase0 = self._now() - self._frozen_phase

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
        the overlay color; otherwise it is the representative base color (first
        pixel of the last rendered base framebuffer).
        """
        return self._active_color()

    # --- per-tick render body + loop ------------------------------------

    async def tick_once(self) -> None:
        """Per-tick render body.

        Render the active framebuffer (solid overlay if a flash is active, else
        the mode-driven per-pixel base), encode it ON the event loop,
        dirty-check, and offload ONLY the blocking driver write via
        ``asyncio.to_thread`` (D-01, LED-07).
        """
        now = self._now()
        if self._overlay_fn is not None and now < self._overlay_until:
            # Rainbow overlay-fn renders a per-pixel hue cycle
            frame = self._overlay_fn(now - self._overlay_started_at, settings.led_count)
        elif self._overlay is not None and now < self._overlay_until:
            # D-11: flashes stay solid (no per-pixel / cross-fade).
            frame = [self._overlay] * settings.led_count
        else:
            # Auto-restore: clear expired overlay, resume base
            self._overlay = None
            self._overlay_fn = None
            frame = self._render_base(now, settings.led_count)
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
        """Overlay-while-active else the representative base color.

        D-07 / D-08: overlay wins until ``_overlay_until``; once expired the
        overlay is cleared on this call so the base resumes on the next tick.

        Phase 33: the representative base color is the first pixel of the last
        rendered base framebuffer (cached in ``_last_base_color``), so observers
        see the live mode color (breathing, beacon, etc.) rather than a stale
        ``_base`` tuple.
        """
        if self._overlay_fn is not None and self._now() < self._overlay_until:
            frame = self._overlay_fn(self._now() - self._overlay_started_at, settings.led_count)
            return frame[0] if frame else (0, 0, 0)
        if self._overlay is not None:
            if self._now() < self._overlay_until:
                return self._overlay
            # Auto-restore: clear the expired overlay.
            self._overlay = None
        return self._last_base_color

    def _render_base(self, now: float, count: int) -> list[tuple[int, int, int]]:
        """Render the mode-driven base framebuffer (D-13) with cross-fade and
        the idle-only health beacon overlay (D-14).

        Pipeline:
        1. Compute the destination frame ``fb_to`` via :meth:`_render_mode`
           (mode dispatch + boot one-shot + error auto-fade).
        2. If a cross-fade is active (D-17), blend ``_fade_from`` -> ``fb_to``
           in PLAIN RGB (Pitfall 1: no gamma inside the blend — the encoder
           gammas the blended result ONCE below the boundary).
        3. If the resolved mode is IDLE and hardware is down, overlay the
           low-amber beacon on pixel 0 (D-14 / LED-21).
        4. Cache the first pixel as ``_last_base_color`` for status reads.
        """
        fb_to = self._render_mode(now, count)

        # D-17 cross-fade between base-mode frames (flashes stay crisp — they
        # are handled in tick_once, never reaching here).
        if (
            self._fade_from is not None
            and self._fade_duration > 0
            and now - self._fade_start < self._fade_duration
        ):
            alpha = (now - self._fade_start) / self._fade_duration
            fb = led_effects.crossfade(self._fade_from, fb_to, alpha)
        else:
            self._fade_from = None
            fb = fb_to

        # D-14: idle-only health beacon. Replaces pixel 0 with a fixed low-amber
        # accent when the resolved mode is IDLE and hardware is down; suppressed
        # by any higher mode.
        if self._mode == Mode.IDLE and self._health_down:
            fb = list(fb)
            fb[0] = self._beacon_color

        self._last_base_color = fb[0] if fb else self._base
        return fb

    def _render_mode(self, now: float, count: int) -> list[tuple[int, int, int]]:
        """Dispatch to the active mode's pure render function (D-13).

        Handles the boot one-shot (D-10 / LED-18) and the error auto-fade
        lifecycle (D-15 / D-16 / LED-15) before falling through to the mode
        dispatch. IDLE renders ``[_base]`` so the Phase 32 ``set_base`` contract
        (and the existing ``/led`` route) is preserved byte-for-byte.
        """
        # D-10 / LED-18: engine-internal boot one-shot. Armed by
        # set_mode("boot") (or the lifespan trigger in plan 06). Renders the
        # wipe until ``led_boot_wipe_s`` elapses, then auto-settles.
        if self._boot_started_at is not None and not self._boot_done:
            elapsed = now - self._boot_started_at
            if elapsed < settings.led_boot_wipe_s:
                return led_effects.boot_wipe(elapsed, count, self._boot_color)
            # Wipe complete — settle to the resolved mode (idle by default).
            self._boot_done = True

        mode = self._mode

        # D-15 / D-16: error is the highest base priority; after its lifetime it
        # auto-transitions to IDLE with a cross-fade (clear-on-action is
        # automatic since any set_mode replaces the mode).
        if (
            mode == Mode.ERROR
            and (now - self._mode_started_at) >= self._error_lifetime_s
        ):
            self._mode = Mode.IDLE
            self._base = self._idle_rgb
            self._mode_started_at = now
            self._fade_from = led_effects.error_amber(
                now - self._mode_started_at + self._error_lifetime_s,
                count,
                self._error_lifetime_s,
            )
            self._fade_start = now - self._period
            self._fade_duration = settings.led_crossfade_s
            mode = Mode.IDLE

        if mode == Mode.IDLE:
            # IDLE renders the persistent base slot (Phase 32 contract). When
            # entered via set_mode("idle"), _base was loaded with the idle glow.
            return [self._base] * count
        if mode == Mode.PLAYBACK:
            # D-12: frozen phase while paused; otherwise time since _phase0.
            effective = self._frozen_phase if self._paused else (now - self._phase0)
            return led_effects.breathe(effective, count, self._mode_color)
        if mode == Mode.THINKING:
            return led_effects.comet(now, count, self._thinking_color)
        if mode == Mode.PROGRESS:
            return led_effects.progress(
                now, count, self._mode_color, self._progress_i, self._progress_n
            )
        if mode == Mode.PARAM:
            return led_effects.param_fill(now, count, self._param_count)
        if mode == Mode.ERROR:
            elapsed = now - self._mode_started_at
            return led_effects.error_amber(now, count, elapsed)
        return [self._base] * count

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
