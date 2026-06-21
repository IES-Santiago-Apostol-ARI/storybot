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
from app.services.led_animator import LedAnimator
from fastapi.testclient import TestClient

from app.main import app
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
