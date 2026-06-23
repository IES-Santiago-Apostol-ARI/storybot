"""Tests for GpioDispatcher service and system_control.poweroff().

Verifies:
- GpioDispatcher consumes from gpio_events queue
- Debounce guard prevents rapid re-trigger (BTN-02)
- Power-off button triggers rainbow LED feedback then poweroff (BTN-01, BTN-05)
- Kiosk event queue receives dispatched events (BTN-07)
- system_control.poweroff() runs the configured command
- POST /api/system/poweroff endpoint returns 200
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


class TestGpioDispatcher:
    """GpioDispatcher event loop, debounce, kiosk_events queue."""

    @pytest.mark.asyncio
    async def test_dispatcher_consumes_gpio_events(self):
        """GpioDispatcher reads from gpio_events and dispatches to handlers."""
        from app.services import gpio_dispatcher

        gpio_events: asyncio.Queue = asyncio.Queue()
        kiosk_events: asyncio.Queue = asyncio.Queue()

        dispatcher = gpio_dispatcher.GpioDispatcher(
            gpio_events=gpio_events,
            kiosk_events=kiosk_events,
        )

        # Trigger a "power" button event
        gpio_events.put_nowait("power")

        # Let dispatcher process one event
        await dispatcher._handle_event("power")

        # Kiosk event queue should have received the event
        assert not kiosk_events.empty()
        event = kiosk_events.get_nowait()
        assert event["button"] == "power"

    @pytest.mark.asyncio
    async def test_debounce_prevents_rapid_retrigger(self):
        """BTN-02: Power-off requires 3-second hold; debounce blocks rapid events."""
        from app.services import gpio_dispatcher

        gpio_events: asyncio.Queue = asyncio.Queue()
        kiosk_events: asyncio.Queue = asyncio.Queue()

        dispatcher = gpio_dispatcher.GpioDispatcher(
            gpio_events=gpio_events,
            kiosk_events=kiosk_events,
        )

        # First event should be accepted
        await dispatcher._handle_event("power")
        assert not kiosk_events.empty()
        kiosk_events.get_nowait()

        # Immediate second event should be debounced (dropped)
        await dispatcher._handle_event("power")
        assert kiosk_events.empty(), "Second rapid event should be debounced"

    @pytest.mark.asyncio
    async def test_debounce_resets_after_timeout(self):
        """After debounce_ms elapses, a new event is accepted."""
        from app.services import gpio_dispatcher

        gpio_events: asyncio.Queue = asyncio.Queue()
        kiosk_events: asyncio.Queue = asyncio.Queue()

        dispatcher = gpio_dispatcher.GpioDispatcher(
            gpio_events=gpio_events,
            kiosk_events=kiosk_events,
        )

        # First event accepted
        await dispatcher._handle_event("power")
        kiosk_events.get_nowait()

        # Advance time past debounce window (100ms > 50ms default)
        await asyncio.sleep(0.1)

        # Second event should now be accepted
        await dispatcher._handle_event("power")
        assert not kiosk_events.empty(), "Event after debounce timeout should pass"

    @pytest.mark.asyncio
    async def test_power_button_triggers_rainbow_feedback(self):
        """BTN-05: Button press feedback LED animation starts on press."""
        from app.services import gpio_dispatcher

        gpio_events: asyncio.Queue = asyncio.Queue()
        kiosk_events: asyncio.Queue = asyncio.Queue()

        mock_animator = MagicMock()
        mock_animator.rainbow = MagicMock()

        dispatcher = gpio_dispatcher.GpioDispatcher(
            gpio_events=gpio_events,
            kiosk_events=kiosk_events,
            led_animator=mock_animator,
        )

        await dispatcher._handle_event("power")

        # Rainbow feedback should have been triggered
        mock_animator.rainbow.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_power_button_no_rainbow(self):
        """Non-power buttons do not trigger rainbow feedback."""
        from app.services import gpio_dispatcher

        gpio_events: asyncio.Queue = asyncio.Queue()
        kiosk_events: asyncio.Queue = asyncio.Queue()

        mock_animator = MagicMock()
        mock_animator.rainbow = MagicMock()

        dispatcher = gpio_dispatcher.GpioDispatcher(
            gpio_events=gpio_events,
            kiosk_events=kiosk_events,
            led_animator=mock_animator,
        )

        await dispatcher._handle_event("interrupt")

        # No rainbow for non-power buttons
        mock_animator.rainbow.assert_not_called()

    @pytest.mark.asyncio
    async def test_dispatcher_run_loop(self):
        """GpioDispatcher.run() processes events from gpio_events queue."""
        from app.services import gpio_dispatcher

        gpio_events: asyncio.Queue = asyncio.Queue()
        kiosk_events: asyncio.Queue = asyncio.Queue()

        dispatcher = gpio_dispatcher.GpioDispatcher(
            gpio_events=gpio_events,
            kiosk_events=kiosk_events,
        )

        # Enqueue an event
        gpio_events.put_nowait("interrupt")

        # Start the run loop in a task
        task = asyncio.create_task(dispatcher.run())

        # Give it time to process
        await asyncio.sleep(0.1)

        # Cancel and gather
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Event should have been dispatched
        assert not kiosk_events.empty()
        event = kiosk_events.get_nowait()
        assert event["button"] == "interrupt"

    @pytest.mark.asyncio
    async def test_kiosk_event_queue_not_blocking(self):
        """BTN-07: Kiosk event queue processes events without blocking UI."""
        from app.services import gpio_dispatcher

        gpio_events: asyncio.Queue = asyncio.Queue()
        kiosk_events: asyncio.Queue = asyncio.Queue()

        dispatcher = gpio_dispatcher.GpioDispatcher(
            gpio_events=gpio_events,
            kiosk_events=kiosk_events,
        )

        # Enqueue multiple events rapidly
        for btn in ["power", "interrupt", "image", "animation"]:
            gpio_events.put_nowait(btn)

        task = asyncio.create_task(dispatcher.run())
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # All events should be in the kiosk queue
        assert kiosk_events.qsize() == 4


class TestSystemControl:
    """system_control.poweroff() function."""

    @pytest.mark.asyncio
    async def test_poweroff_runs_command(self):
        """system_control.poweroff() executes the configured poweroff command."""
        from app.services import system_control

        with patch("subprocess.Popen") as mock_popen:
            await system_control.poweroff()
            mock_popen.assert_called_once()

    @pytest.mark.asyncio
    async def test_poweroff_uses_configured_command(self):
        """poweroff uses the poweroff_cmd from settings."""
        from app.services import system_control

        with patch("subprocess.Popen") as mock_popen:
            await system_control.poweroff()
            call_args = mock_popen.call_args
            # The command should be the configured poweroff_cmd
            assert call_args[0][0] == ["/usr/bin/sudo", "/sbin/poweroff"]

    @pytest.mark.asyncio
    async def test_poweroff_starts_detached_process(self):
        """poweroff starts a detached process (start_new_session=True)."""
        from app.services import system_control

        with patch("subprocess.Popen") as mock_popen:
            await system_control.poweroff()
            call_kwargs = mock_popen.call_args[1]
            assert call_kwargs.get("start_new_session") is True


class TestImageButtonHandler:
    """Image button handler (BTN-03, BTN-04) in GpioDispatcher.

    Verifies:
    - Image button triggers cover generation for currently playing story
    - Cover generation runs in background without blocking dispatcher loop
    - Drop-on-busy guard when swap_orchestrator returns None
    - D-10 edge cases: story_id=None, swap_orchestrator unavailable
    """

    @pytest.mark.asyncio
    async def test_image_button_triggers_cover_generation(self):
        """BTN-03: Image button triggers cover gen for currently playing story."""
        from app.services import gpio_dispatcher

        gpio_events: asyncio.Queue = asyncio.Queue()
        kiosk_events: asyncio.Queue = asyncio.Queue()

        mock_orchestrator = MagicMock()
        mock_orchestrator.generate_cover_for_story = AsyncMock(
            return_value=(MagicMock(), MagicMock(), 5.0)
        )

        dispatcher = gpio_dispatcher.GpioDispatcher(
            gpio_events=gpio_events,
            kiosk_events=kiosk_events,
            swap_orchestrator=mock_orchestrator,
        )
        # Set the currently playing story ID
        dispatcher.current_story_id = "story-123"

        await dispatcher._handle_event("image")

        # Let the background task start
        await asyncio.sleep(0)

        mock_orchestrator.generate_cover_for_story.assert_called_once()
        call_kwargs = mock_orchestrator.generate_cover_for_story.call_args
        assert call_kwargs[0][0] == "story-123"

    @pytest.mark.asyncio
    async def test_image_button_uses_fallback_prompt(self):
        """Image button uses cover_prompt_builder for title-based fallback prompt."""
        from app.services import gpio_dispatcher

        gpio_events: asyncio.Queue = asyncio.Queue()
        kiosk_events: asyncio.Queue = asyncio.Queue()

        mock_orchestrator = MagicMock()
        mock_orchestrator.generate_cover_for_story = AsyncMock(
            return_value=(MagicMock(), MagicMock(), 3.0)
        )

        dispatcher = gpio_dispatcher.GpioDispatcher(
            gpio_events=gpio_events,
            kiosk_events=kiosk_events,
            swap_orchestrator=mock_orchestrator,
        )
        dispatcher.current_story_id = "story-456"

        await dispatcher._handle_event("image")

        # Let the background task start
        await asyncio.sleep(0)

        # Verify prompt was generated (positive and negative are non-empty strings)
        call_kwargs = mock_orchestrator.generate_cover_for_story.call_args
        positive = call_kwargs[0][1]
        negative = call_kwargs[0][2]
        assert isinstance(positive, str) and len(positive) > 0
        assert isinstance(negative, str) and len(negative) > 0

    @pytest.mark.asyncio
    async def test_image_button_runs_in_background(self):
        """BTN-04: Cover generation runs in background without blocking dispatcher."""
        from app.services import gpio_dispatcher

        gpio_events: asyncio.Queue = asyncio.Queue()
        kiosk_events: asyncio.Queue = asyncio.Queue()

        mock_orchestrator = MagicMock()
        mock_orchestrator.generate_cover_for_story = AsyncMock(
            return_value=(MagicMock(), MagicMock(), 10.0)
        )

        dispatcher = gpio_dispatcher.GpioDispatcher(
            gpio_events=gpio_events,
            kiosk_events=kiosk_events,
            swap_orchestrator=mock_orchestrator,
        )
        dispatcher.current_story_id = "story-789"

        await dispatcher._handle_event("image")

        # Kiosk event should be enqueued immediately (non-blocking)
        assert not kiosk_events.empty()
        event = kiosk_events.get_nowait()
        assert event["button"] == "image"

    @pytest.mark.asyncio
    async def test_image_button_drop_on_busy(self):
        """Drop-on-busy guard: when swap_orchestrator returns None, event is dropped."""
        from app.services import gpio_dispatcher

        gpio_events: asyncio.Queue = asyncio.Queue()
        kiosk_events: asyncio.Queue = asyncio.Queue()

        mock_orchestrator = MagicMock()
        mock_orchestrator.generate_cover_for_story = AsyncMock(
            return_value=(None, None, None)
        )

        dispatcher = gpio_dispatcher.GpioDispatcher(
            gpio_events=gpio_events,
            kiosk_events=kiosk_events,
            swap_orchestrator=mock_orchestrator,
        )
        dispatcher.current_story_id = "story-busy"

        await dispatcher._handle_event("image")

        # Let the background task start
        await asyncio.sleep(0)

        # Orchestrator was called (busy check happened)
        mock_orchestrator.generate_cover_for_story.assert_called_once()
        # Kiosk event still enqueued (button press acknowledged)
        assert not kiosk_events.empty()

    @pytest.mark.asyncio
    async def test_image_button_no_story_id(self):
        """D-10: Handle story_id=None gracefully — no crash, no generation."""
        from app.services import gpio_dispatcher

        gpio_events: asyncio.Queue = asyncio.Queue()
        kiosk_events: asyncio.Queue = asyncio.Queue()

        mock_orchestrator = MagicMock()
        mock_orchestrator.generate_cover_for_story = AsyncMock(
            return_value=(MagicMock(), MagicMock(), 5.0)
        )

        dispatcher = gpio_dispatcher.GpioDispatcher(
            gpio_events=gpio_events,
            kiosk_events=kiosk_events,
            swap_orchestrator=mock_orchestrator,
        )
        # No current_story_id set (None)
        dispatcher.current_story_id = None

        await dispatcher._handle_event("image")

        # Orchestrator should NOT be called when no story is playing
        mock_orchestrator.generate_cover_for_story.assert_not_called()
        # But kiosk event should still be dispatched
        assert not kiosk_events.empty()

    @pytest.mark.asyncio
    async def test_image_button_no_orchestrator(self):
        """D-10: Handle swap_orchestrator unavailability gracefully."""
        from app.services import gpio_dispatcher

        gpio_events: asyncio.Queue = asyncio.Queue()
        kiosk_events: asyncio.Queue = asyncio.Queue()

        dispatcher = gpio_dispatcher.GpioDispatcher(
            gpio_events=gpio_events,
            kiosk_events=kiosk_events,
            swap_orchestrator=None,
        )
        dispatcher.current_story_id = "story-no-orch"

        await dispatcher._handle_event("image")

        # No crash — graceful degradation
        # Kiosk event should still be dispatched
        assert not kiosk_events.empty()

    @pytest.mark.asyncio
    async def test_image_button_orchestrator_exception(self):
        """D-10: Handle swap_orchestrator exception gracefully."""
        from app.services import gpio_dispatcher

        gpio_events: asyncio.Queue = asyncio.Queue()
        kiosk_events: asyncio.Queue = asyncio.Queue()

        mock_orchestrator = MagicMock()
        mock_orchestrator.generate_cover_for_story = AsyncMock(
            side_effect=RuntimeError("SD worker crashed")
        )

        dispatcher = gpio_dispatcher.GpioDispatcher(
            gpio_events=gpio_events,
            kiosk_events=kiosk_events,
            swap_orchestrator=mock_orchestrator,
        )
        dispatcher.current_story_id = "story-crash"

        await dispatcher._handle_event("image")

        # Let the background task start and complete
        await asyncio.sleep(0)

        # No crash — exception caught
        # Kiosk event should still be dispatched
        assert not kiosk_events.empty()

    @pytest.mark.asyncio
    async def test_image_button_debounce(self):
        """Image button is subject to the same debounce guard as other buttons."""
        from app.services import gpio_dispatcher

        gpio_events: asyncio.Queue = asyncio.Queue()
        kiosk_events: asyncio.Queue = asyncio.Queue()

        mock_orchestrator = MagicMock()
        mock_orchestrator.generate_cover_for_story = AsyncMock(
            return_value=(MagicMock(), MagicMock(), 5.0)
        )

        dispatcher = gpio_dispatcher.GpioDispatcher(
            gpio_events=gpio_events,
            kiosk_events=kiosk_events,
            swap_orchestrator=mock_orchestrator,
        )
        dispatcher.current_story_id = "story-debounce"

        # First image press accepted
        await dispatcher._handle_event("image")
        # Let the background task start
        await asyncio.sleep(0)
        assert mock_orchestrator.generate_cover_for_story.call_count == 1

        # Immediate second press should be debounced
        await dispatcher._handle_event("image")
        await asyncio.sleep(0)
        assert mock_orchestrator.generate_cover_for_story.call_count == 1, (
            "Second rapid image press should be debounced"
        )


class TestPoweroffEndpoint:
    """POST /api/system/poweroff endpoint."""

    def test_poweroff_endpoint_returns_200(self):
        """POST /api/system/poweroff returns 200 with status ok."""
        with patch("app.services.system_control.poweroff") as mock_poweroff:
            mock_poweroff.return_value = asyncio.ensure_future(asyncio.sleep(0))
            with TestClient(app) as client:
                response = client.post("/api/system/poweroff")
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "ok"

    def test_poweroff_endpoint_calls_system_control(self):
        """POST /api/system/poweroff calls system_control.poweroff()."""
        with patch("app.services.system_control.poweroff") as mock_poweroff:
            mock_poweroff.return_value = asyncio.ensure_future(asyncio.sleep(0))
            with TestClient(app) as client:
                client.post("/api/system/poweroff")
                # Verify the call was made (TestClient runs sync, so we check
                # that the endpoint code path invoked it)
                assert mock_poweroff.called
