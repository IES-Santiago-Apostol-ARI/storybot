"""Tests for LED animator service.

These tests drive the ``LedAnimator`` engine deterministically via the
``tick_once()`` seam + an injected clock (no wall-clock sleeps, no lifespan).

They assert on the *engine's* own state (``get_color`` / ``_active_color``)
and on the dirty-check by spying on ``_write`` invocation count — NOT on the
underlying mock driver's color (per Plan 32-02 A3: the engine's ``_write`` on
the mock is an explicit no-op because it receives encoded ``bytes``, not RGB
ints; it does NOT call ``MockLEDService.set_color``).
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.led_animator import LedAnimator
from app.services.led_controller import MockLEDService


class _FakeClock:
    """Mutable monotonic-time source mirroring tests/conftest.py.

    Advances only when explicitly moved via ``advance``.
    """

    def __init__(self) -> None:
        self.now: float = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def fake_clock() -> _FakeClock:
    """A mutable monotonic clock for deterministic animation testing."""
    return _FakeClock()


@pytest.fixture
def mock_led_service():
    """Mock LED driver surface (public surface stays byte-for-byte unchanged)."""
    return MockLEDService()


@pytest.fixture
def led_animator(mock_led_service, fake_clock):
    """LedAnimator instance driven by a mock service and fake clock."""
    return LedAnimator(led_service=mock_led_service, now=fake_clock)


class TestLedAnimatorContract:
    """Tests for LedAnimator requirements (LED-06, LED-08)."""

    @pytest.mark.asyncio
    async def test_startup_shutdown_lifecycle(self):
        """
        LED-06: Test the animator's lifecycle within the app lifespan.
        Selector: -k startup_shutdown
        """
        with TestClient(app):
            # Post-startup: Animator should be running as a background task
            # in app.state
            animator = app.state.led_animator
            assert animator is not None

            # Check if the run loop is actually scheduled
            # We expect animator._run_task to be a Task object that is not done
            assert hasattr(animator, "_run_task")
            assert not animator._run_task.done()

        # Post-shutdown: Task should be cancelled and gathered
        assert animator._run_task.cancelled() or animator._run_task.done()

    @pytest.mark.asyncio
    async def test_preempt_restore_logic(
        self, led_animator, mock_led_service, fake_clock
    ):
        """
        LED-08: Test priority preempt and restoration.
        Selector: -k preempt_restore

        Asserts on the engine's own state (``get_color`` returns the active
        rendered color during ticks). D-08/D-07/D-10.
        """
        # 1. Base color setup (Blue)
        await led_animator.set_base(0, 0, 255)
        await led_animator.tick_once()
        assert led_animator.get_color() == (0, 0, 255)

        # 2. Preempt with flash (Red for 100ms)
        led_animator.flash(255, 0, 0, ms=100)
        await led_animator.tick_once()
        # D-08: Flash wins on the next tick (overlay preempts base)
        assert led_animator.get_color() == (255, 0, 0)

        # 3. Change base while flash is active
        await led_animator.set_base(0, 255, 0)  # Green
        await led_animator.tick_once()
        # D-10: Flash must keep playing despite base change
        assert led_animator.get_color() == (255, 0, 0)

        # 4. Advance clock past flash duration
        fake_clock.advance(0.101)
        await led_animator.tick_once()
        # D-07/D-10: Restore to the NEW base (Green), not the old base
        assert led_animator.get_color() == (0, 255, 0)

    @pytest.mark.asyncio
    async def test_dirty_check_optimization(self, led_animator, mock_led_service):
        """
        LED-06: Driver writes only fire when encoded frames actually differ.
        Selector: -k dirty_check

        Spies on ``_write`` invocation count (D-06 value-equality dirty-check).
        """
        # Spy on the engine's _write — the sole SPI-write seam.
        led_animator._write = MagicMock(wraps=led_animator._write)

        # Tick 1: First write (Black -> Red)
        await led_animator.set_base(255, 0, 0)
        await led_animator.tick_once()
        assert led_animator._write.call_count == 1

        # Tick 2: Same color -> no new write (dirty-check, D-06)
        await led_animator.tick_once()
        assert led_animator._write.call_count == 1  # Still 1

        # Tick 3: Color change (Red -> Blue) -> new write
        await led_animator.set_base(0, 0, 255)
        await led_animator.tick_once()
        assert led_animator._write.call_count == 2

    @pytest.mark.asyncio
    async def test_set_base_clamps_values(self, led_animator, mock_led_service):
        """Test that input channels are clamped to 0-255."""
        await led_animator.set_base(300, -50, 128)
        await led_animator.tick_once()
        assert led_animator.get_color() == (255, 0, 128)

        led_animator.flash(500, 100, -100, ms=100)
        await led_animator.tick_once()
        assert led_animator.get_color() == (255, 100, 0)

    @pytest.mark.asyncio
    async def test_shutdown_cancels_loop_before_closing_hardware(self, monkeypatch):
        """CR-01: the animation loop is cancelled+gathered BEFORE
        hardware.shutdown() closes the SPI device.

        Selector: -k shutdown_cancels_loop

        The animator is a *continuous* writer, so if hardware.shutdown() (which
        closes the SPI ``_writer``) ran first, the loop would keep writing to a
        closed device and repaint over the shutdown turn_off(). We record, at the
        moment the LED driver is shut down, whether the animator run-task has
        already stopped — it must have.
        """
        captured = {}

        class _RecordingLED(MockLEDService):
            async def shutdown(self) -> None:
                animator = getattr(app.state, "led_animator", None)
                run_task = getattr(animator, "_run_task", None)
                captured["loop_stopped_at_hw_shutdown"] = (
                    run_task is None or run_task.done()
                )
                await super().shutdown()

        # detect_hardware does `from app.services.led_controller import
        # create_led_service`, so patch the source module attribute.
        monkeypatch.setattr(
            "app.services.led_controller.create_led_service",
            lambda: _RecordingLED(),
        )

        with TestClient(app):
            assert app.state.led_animator is not None

        assert captured.get("loop_stopped_at_hw_shutdown") is True

    @pytest.mark.asyncio
    async def test_set_driver_repoints_engine_and_resets_dirty_cache(self, fake_clock):
        """CR-02: set_driver re-points the engine at a freshly-probed driver
        (after /rescan) and clears the dirty-check cache so the next tick writes
        to the NEW driver instead of the orphaned old one.

        Selector: -k set_driver
        """

        class _Writer:
            def __init__(self) -> None:
                self.frames: list[bytes] = []

            def write(self, encoded: bytes) -> None:
                self.frames.append(encoded)

        class _Driver:
            def __init__(self) -> None:
                self._writer = _Writer()

        old, new = _Driver(), _Driver()
        animator = LedAnimator(led_service=old, now=fake_clock)

        await animator.set_base(255, 0, 0)
        await animator.tick_once()
        assert len(old._writer.frames) == 1  # wrote to the old driver
        assert animator._last_written is not None

        # Simulate a rescan re-pointing the sole writer at the new driver.
        animator.set_driver(new)
        assert animator._led_service is new
        assert animator._last_written is None  # dirty cache reset (CR-02)

        # Next tick re-writes the current frame to the NEW driver only.
        await animator.tick_once()
        assert len(new._writer.frames) == 1
        assert len(old._writer.frames) == 1  # old driver untouched after re-point

# ============================================================
# Phase 33 RED tests — engine extensions (set_mode, set_health)
# These reference not-yet-existing APIs and are expected to FAIL
# until plan 03 lands.
# ============================================================

class TestLedAnimatorMode:
    """Phase 33 engine extension tests (RED until plan 03)."""

    @pytest.mark.asyncio
    async def test_flash_rate_limit(self, led_animator, fake_clock):
        """LED-23: Flash rate limit — second flash within 333ms is dropped.

        Fire flash at t=0; advance to t=0.332s, fire again — assert dropped.
        Advance past 0.333s, fire again — assert accepted.
        """
        led_animator.flash(255, 0, 0, ms=100)
        await led_animator.tick_once()
        assert led_animator.get_color() == (255, 0, 0)

        # Second flash within rate limit — should be dropped
        fake_clock.advance(0.332)
        led_animator.flash(0, 255, 0, ms=100)
        await led_animator.tick_once()
        # Should still show the first flash (or base), NOT the second
        assert led_animator.get_color() != (0, 255, 0)

        # Past rate limit — should be accepted
        fake_clock.advance(0.002)  # now 0.334s from first flash
        led_animator.flash(0, 0, 255, ms=100)
        await led_animator.tick_once()
        assert led_animator.get_color() == (0, 0, 255)

    @pytest.mark.asyncio
    async def test_idle_static_no_rewrite(self, led_animator, mock_led_service, fake_clock):
        """LED-16: Idle mode is static — dirty-check suppresses bus traffic.

        Set idle mode; tick many times; assert _write.call_count == 1
        (only the first paint, no subsequent writes).
        """
        led_animator.set_mode("idle")
        # Spy on _write
        led_animator._write = MagicMock(wraps=led_animator._write)

        await led_animator.tick_once()
        first_count = led_animator._write.call_count

        # Advance clock and tick many more times
        for _ in range(10):
            fake_clock.advance(0.1)
            await led_animator.tick_once()

        # Static idle should not rewrite
        assert led_animator._write.call_count == first_count

    @pytest.mark.asyncio
    async def test_pause_hold_resume(self, led_animator, fake_clock):
        """LED-11: Pause holds frame steady; resume is phase-continuous.

        Set playback mode; tick to mid-breath; pause — assert frame holds
        steady (no oscillation); resume — assert breathing resumes without
        a hard-cut jump to full brightness.
        """
        led_animator.set_mode("playback", color=(255, 0, 0))
        await led_animator.tick_once()
        color_before_pause = led_animator.get_color()

        # Pause — frame should hold steady
        led_animator.set_mode("pause")
        await led_animator.tick_once()
        color_after_pause = led_animator.get_color()

        # Advance clock — frame should NOT change while paused
        fake_clock.advance(2.0)
        await led_animator.tick_once()
        color_while_paused = led_animator.get_color()
        assert color_while_paused == color_after_pause, "Pause should hold frame steady"

        # Resume — breathing should resume phase-continuous (no hard-cut)
        led_animator.set_mode("resume")
        await led_animator.tick_once()
        color_after_resume = led_animator.get_color()
        # Should not jump to full brightness
        assert color_after_resume != (255, 0, 0), "Resume should be phase-continuous"

    @pytest.mark.asyncio
    async def test_ended_crossfade_to_idle(self, led_animator, fake_clock):
        """LED-12, LED-22: Ended mode crossfades to idle, not hard-cut.

        Set playback; set ended — assert intermediate blended value
        (not the destination immediately).
        """
        led_animator.set_mode("playback", color=(255, 0, 0))
        await led_animator.tick_once()
        playback_color = led_animator.get_color()

        # Set ended — should crossfade, not hard-cut
        led_animator.set_mode("ended")
        await led_animator.tick_once()
        ended_color = led_animator.get_color()

        # Should be a blended value (not idle glow yet, not playback)
        assert ended_color != playback_color, "Should not be playback color"
        # Should not be idle glow yet (crossfade in progress)
        led_animator.set_mode("idle")
        await led_animator.tick_once()
        idle_color = led_animator.get_color()
        assert ended_color != idle_color, "Should not be idle glow yet"

    @pytest.mark.asyncio
    async def test_crossfade_intermediate(self, led_animator, fake_clock):
        """LED-22: Generic mode change yields blended intermediate.

        idle → thinking should produce a blended framebuffer at midpoint.
        """
        led_animator.set_mode("idle")
        await led_animator.tick_once()
        idle_color = led_animator.get_color()

        led_animator.set_mode("thinking")
        await led_animator.tick_once()
        intermediate_color = led_animator.get_color()

        # Should be between idle and thinking colors
        assert intermediate_color != idle_color, "Should not be idle color"

    @pytest.mark.asyncio
    async def test_beacon_idle_only(self, led_animator, fake_clock):
        """LED-21: Beacon only renders in idle mode, suppressed in playback.

        Call set_health(down=True); idle → beacon appears; playback → suppressed.
        """
        led_animator.set_health(down=True)

        # Idle mode — beacon should appear
        led_animator.set_mode("idle")
        await led_animator.tick_once()
        idle_with_beacon = led_animator.get_color()

        # Playback mode — beacon suppressed
        led_animator.set_mode("playback", color=(255, 0, 0))
        await led_animator.tick_once()
        playback_color = led_animator.get_color()

        # Beacon should be different from idle (suppressed in playback)
        assert playback_color != idle_with_beacon, "Beacon should be suppressed in playback"

        # Return to idle — beacon reappears
        led_animator.set_mode("idle")
        await led_animator.tick_once()
        idle_beacon_again = led_animator.get_color()
        assert idle_beacon_again == idle_with_beacon, "Beacon should reappear in idle"

    @pytest.mark.asyncio
    async def test_tap_flash_overlay(self, led_animator, fake_clock):
        """LED-13: Tap flash uses neutral/white confirm color."""
        led_animator.flash_tap()
        await led_animator.tick_once()
        color = led_animator.get_color()
        # Tap flash should be white/neutral
        assert color[0] > 200 and color[1] > 200 and color[2] > 200

    @pytest.mark.asyncio
    async def test_go_flash_distinct(self, led_animator, fake_clock):
        """LED-14: GO flash uses distinct green color, longer duration."""
        led_animator.flash_go()
        await led_animator.tick_once()
        color = led_animator.get_color()
        # GO flash should be green-dominant
        assert color[1] > color[0] and color[1] > color[2]

    @pytest.mark.asyncio
    async def test_error_overrides_then_autofades(self, led_animator, fake_clock):
        """LED-15: Error overrides playback, then auto-fades to idle.

        Set playback; set error — assert amber; advance past auto-fade —
        assert settled to idle. Also: error cleared by new action.
        """
        led_animator.set_mode("playback", color=(255, 0, 0))
        await led_animator.tick_once()

        # Error overrides playback
        led_animator.set_mode("error")
        await led_animator.tick_once()
        error_color = led_animator.get_color()
        # Should be amber (not red, not blue)
        assert error_color[0] > error_color[2], "Error should be amber, not blue"
        assert error_color[1] > error_color[2], "Error should have green component"

        # Advance past auto-fade duration — should settle to idle
        fake_clock.advance(5.0)
        await led_animator.tick_once()
        faded_color = led_animator.get_color()
        assert faded_color != error_color, "Error should auto-fade"

        # Error cleared by new action
        led_animator.set_mode("playback", color=(0, 255, 0))
        await led_animator.tick_once()
        new_color = led_animator.get_color()
        assert new_color[1] > new_color[0], "New action should clear error"

    @pytest.mark.asyncio
    async def test_boot_sweep_then_idle(self, led_animator, fake_clock):
        """LED-18: Boot sweep renders then auto-settles to idle.

        Fresh engine on first ticks renders boot wipe (increasing lit prefix),
        then auto-settles to idle once wipe duration elapses.
        """
        # Fresh engine — should start with boot sweep
        led_animator.set_mode("boot")
        await led_animator.tick_once()
        boot_color_1 = led_animator.get_color()

        # Advance — should light more pixels
        fake_clock.advance(0.3)
        await led_animator.tick_once()
        boot_color_2 = led_animator.get_color()

        # After wipe duration — should settle to idle
        fake_clock.advance(1.0)
        await led_animator.tick_once()
        settled_color = led_animator.get_color()

        # Should have changed from boot to idle
        assert settled_color != boot_color_1, "Should settle from boot to idle"

# ============================================================
# Phase 35-03 RED tests — rainbow one-shot LED effect (ANIM-01/02)
# ============================================================

class TestLedAnimatorRainbow:
    """Rainbow one-shot overlay lifecycle tests (RED until plan 35-03)."""

    @pytest.mark.asyncio
    async def test_rainbow_oneshot_lifecycle(self, led_animator, fake_clock):
        """ANIM-01: Rainbow sets a transient overlay that cycles hues across
        the strip for duration_ms, then auto-clears and resumes base mode.

        Call animator.rainbow(duration_ms=500); tick while active — assert
        distinct hue frames (not a single solid color); advance past duration
        — assert overlay cleared and base resumed.
        """
        # Set a known base color
        await led_animator.set_base(0, 128, 255)
        await led_animator.tick_once()
        base_color = led_animator.get_color()

        # Fire rainbow overlay
        led_animator.rainbow(duration_ms=500)
        await led_animator.tick_once()
        rainbow_color_1 = led_animator.get_color()

        # Rainbow should be different from base (distinct hue frames)
        assert rainbow_color_1 != base_color, "Rainbow should differ from base color"

        # Advance a bit — should still be in rainbow (different frame)
        fake_clock.advance(0.1)
        await led_animator.tick_once()
        rainbow_color_2 = led_animator.get_color()
        assert rainbow_color_2 != base_color, "Rainbow should still be active"

        # Advance past duration — overlay should clear, base resumes
        fake_clock.advance(0.6)  # well past 500ms
        await led_animator.tick_once()
        after_rainbow = led_animator.get_color()
        assert after_rainbow == base_color, "Base color should resume after rainbow expires"

    @pytest.mark.asyncio
    async def test_rainbow_returns_to_base(self, led_animator, fake_clock):
        """ANIM-02: After rainbow expiry, _overlay_fn is cleared and color
        returns to the base mode.

        Set a known base color; fire rainbow; advance past expiry — assert
        _overlay_fn is None and color returns to base.
        """
        await led_animator.set_base(128, 0, 255)
        await led_animator.tick_once()
        base_color = led_animator.get_color()

        # Fire rainbow
        led_animator.rainbow(duration_ms=300)
        await led_animator.tick_once()

        # Advance past expiry
        fake_clock.advance(0.5)
        await led_animator.tick_once()

        # Overlay should be cleared
        assert led_animator._overlay_fn is None, "_overlay_fn should be None after expiry"
        # Color should return to base
        assert led_animator.get_color() == base_color, "Color should return to base"
