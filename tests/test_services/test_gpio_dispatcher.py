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
from unittest.mock import MagicMock, patch

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
