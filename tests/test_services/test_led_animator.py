"""Tests for LED animator service (TDD Wave 0).

These tests encode the contract for the LedAnimator engine before implementation.
They are guarded by xfail until the engine and wiring are implemented in Plans 32-02/03.
"""

import asyncio
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

# TDD Guard: LedAnimator is created in Plan 32-02
try:
    from app.services.led_animator import LedAnimator
except ImportError:
    LedAnimator = None


from app.services.led_controller import MockLEDService
from app.main import app


class _FakeClock:
    """Mutable monotonic-time source mirroring tests/conftest.py.
    Advances only when explicitly moved.
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
    """Mock LED driver surface."""
    return MockLEDService()


@pytest.fixture
def led_animator(mock_led_service, fake_clock):
    """LedAnimator instance driven by a mock service and fake clock."""
    if LedAnimator is None:
        pytest.skip("LedAnimator not implemented yet")
    return LedAnimator(led_service=mock_led_service, now=fake_clock)


class TestLedAnimatorContract:
    """TDD stubs for LedAnimator requirements (LED-06..LED-09)."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(strict=False, reason="lifespan wiring lands in 32-03")
    async def test_startup_shutdown_lifecycle(self):
        """
        LED-06: Test the animator's lifecycle within the app lifespan.
        Selector: -k startup_shutdown
        """
        with TestClient(app):
            # Post-startup: Animator should be running as a background task in app.state
            animator = app.state.led_animator
            assert animator is not None
            
            # Check if the run loop is actually scheduled
            # We expect animator._run_task to be a Task object that is not done
            assert hasattr(animator, "_run_task")
            assert not animator._run_task.done()

        # Post-shutdown: Task should be cancelled and gathered
        assert animator._run_task.cancelled() or animator._run_task.done()

    @pytest.mark.asyncio
    @pytest.mark.xfail(strict=False, reason="LedAnimator not implemented until 32-02")
    async def test_preempt_restore_logic(self, led_animator, mock_led_service, fake_clock):
        """
        LED-08: Test priority preempt and restoration.
        Selector: -k preempt_restore
        """
        # 1. Base color setup
        led_animator.set_base(0, 0, 255)  # Blue
        led_animator.tick_once()
        assert mock_led_service.get_color() == (0, 0, 255)

        # 2. Preempt with flash
        led_animator.flash(255, 0, 0, ms=100)  # Red for 100ms
        led_animator.tick_once()
        # D-08: Flash should win on the next tick
        assert mock_led_service.get_color() == (255, 0, 0)

        # 3. Change base while flash is active
        led_animator.set_base(0, 255, 0)  # Green
        led_animator.tick_once()
        # D-10: Flash must keep playing despite base change
        assert mock_led_service.get_color() == (255, 0, 0)

        # 4. Advance clock past flash duration
        fake_clock.advance(0.101)
        led_animator.tick_once()
        # D-07/D-10: Restore to the NEW base (Green)
        assert mock_led_service.get_color() == (0, 255, 0)

    @pytest.mark.asyncio
    @pytest.mark.xfail(strict=False, reason="LedAnimator not implemented until 32-02")
    async def test_dirty_check_optimization(self, led_animator, mock_led_service):
        """
        LED-06: Test that driver writes only fire when colors actually change.
        Selector: -k dirty_check
        """
        # Use a spy on the mock service's set_color
        mock_led_service.set_color = MagicMock(side_effect=mock_led_service.set_color)

        # Tick 1: First write (Black -> Red)
        led_animator.set_base(255, 0, 0)
        led_animator.tick_once()
        assert mock_led_service.set_color.call_count == 1

        # Tick 2: Same color, no write should occur
        led_animator.tick_once()
        assert mock_led_service.set_color.call_count == 1  # Still 1

        # Tick 3: Color change (Red -> Blue)
        led_animator.set_base(0, 0, 255)
        led_animator.tick_once()
        assert mock_led_service.set_color.call_count == 2

    @pytest.mark.asyncio
    @pytest.mark.xfail(strict=False, reason="LedAnimator not implemented until 32-02")
    async def test_set_base_clamps_values(self, led_animator, mock_led_service):
        """Test that input channels are clamped to 0-255."""
        led_animator.set_base(300, -50, 128)
        led_animator.tick_once()
        assert mock_led_service.get_color() == (255, 0, 128)

        led_animator.flash(500, 100, -100, ms=100)
        led_animator.tick_once()
        assert mock_led_service.get_color() == (255, 100, 0)
