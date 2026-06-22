"""Tests for GPIO button service infrastructure.

Verifies the HardwareService Mock/Real pattern, factory branching, mock
trigger seam, and lifespan lifecycle (create + clean cancel).
"""

import asyncio
import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


class TestFactory:
    """GPIOButtonService factory behavior."""

    def test_factory_returns_mock_under_testing(self):
        """With TESTING env set, create_gpio_service() returns MockGPIOButtonService."""
        from app.services.gpio_handler import (
            MockGPIOButtonService,
            create_gpio_service,
        )

        assert os.environ.get("TESTING")
        service = create_gpio_service()
        assert isinstance(service, MockGPIOButtonService)

    def test_factory_never_raises_on_import_failure(self, monkeypatch):
        """When _real_gpio_available returns False, factory returns mock without raising."""
        from app.services.gpio_handler import (
            MockGPIOButtonService,
            create_gpio_service,
        )

        # Force non-testing path and fake probe failure
        monkeypatch.delenv("TESTING", raising=False)
        monkeypatch.setattr(
            "app.services.gpio_handler._real_gpio_available", lambda: False
        )

        service = create_gpio_service()
        assert isinstance(service, MockGPIOButtonService)


class TestMockTrigger:
    """MockGPIOButtonService trigger seam."""

    @pytest.mark.asyncio
    async def test_mock_trigger_enqueues(self):
        """MockGPIOButtonService.trigger('power') enqueues 'power' onto the shared queue."""
        from app.services.gpio_handler import MockGPIOButtonService

        queue: asyncio.Queue = asyncio.Queue()
        service = MockGPIOButtonService()
        await service.initialize(queue)

        service.trigger("power")

        assert not queue.empty()
        assert queue.get_nowait() == "power"


class TestLifespan:
    """GPIO service lifespan lifecycle."""

    @pytest.mark.asyncio
    async def test_gpio_task_clean_cancel(self):
        """Lifespan creates gpio task; after context exits, task is cancelled/done."""
        with TestClient(app):
            assert hasattr(app.state, "gpio_task")
            assert not app.state.gpio_task.done()

        # After shutdown, task should be cancelled or done
        assert app.state.gpio_task.cancelled() or app.state.gpio_task.done()


class TestRealServiceEdgeToQueue:
    """GPIO-02: Real service bridges GPIO edge events to asyncio queue."""

    @pytest.mark.asyncio
    async def test_real_service_bridges_edge_to_queue(self):
        """Verify RealGPIOButtonService configures 4 pins and bridges edges to queue.

        Checks:
        - 4 pins configured in BOARD mode with IN + PUD_UP + bouncetime
        - add_event_detect(FALLING) called for each pin
        - Edge callback fires -> loop.call_soon_threadsafe(queue.put_nowait, name)
        """
        # --- Arrange: mock Jetson.GPIO module ---
        mock_gpio = MagicMock()
        mock_gpio.BOARD = 10
        mock_gpio.IN = 11
        mock_gpio.PUD_UP = 12
        mock_gpio.FALLING = 13

        # Need both "Jetson" and "Jetson.GPIO" in sys.modules so the import
        # statement `import Jetson.GPIO as GPIO` resolves correctly.
        mock_jetson = MagicMock()
        mock_jetson.GPIO = mock_gpio

        with patch.dict("sys.modules", {"Jetson": mock_jetson, "Jetson.GPIO": mock_gpio}):
            from app.services.gpio_handler import RealGPIOButtonService

            service = RealGPIOButtonService()
            queue: asyncio.Queue = asyncio.Queue()

            # --- Act: initialize the real service ---
            await service.initialize(queue)

            # --- Assert 1: setmode(BOARD) called once ---
            mock_gpio.setmode.assert_called_once_with(mock_gpio.BOARD)

            # --- Assert 2: setup() called exactly 4 times (one per pin) ---
            assert mock_gpio.setup.call_count == 4

            # Verify each call: GPIO.setup(pin, IN, pull_up_down=PUD_UP)
            for call in mock_gpio.setup.call_args_list:
                args, kwargs = call
                # Positional: (pin, GPIO.IN)
                assert args[1] == mock_gpio.IN
                # Keyword: pull_up_down=GPIO.PUD_UP
                assert kwargs.get("pull_up_down") == mock_gpio.PUD_UP

            # --- Assert 3: add_event_detect(FALLING) called for each pin ---
            assert mock_gpio.add_event_detect.call_count == 4

            for call in mock_gpio.add_event_detect.call_args_list:
                args, kwargs = call
                # Positional: (pin, GPIO.FALLING)
                assert args[1] == mock_gpio.FALLING
                # callback and bouncetime should be present
                assert "callback" in kwargs
                assert "bouncetime" in kwargs

            # --- Assert 4: Edge callback bridges to queue via call_soon_threadsafe ---
            # Get the callback that was registered for each pin (they're all the same)
            callback = mock_gpio.add_event_detect.call_args_list[0][1]["callback"]

            # The first pin in the map is gpio_power_pin (default 7) -> "power"
            first_pin = mock_gpio.setup.call_args_list[0][0][0]

            # Spy on the real event loop's call_soon_threadsafe to verify it's
            # called with queue.put_nowait and the button name.
            original_cst = service._loop.call_soon_threadsafe
            call_log: list[tuple] = []

            def spy_cst(func, *args):
                call_log.append((func, args))
                return original_cst(func, *args)

            service._loop.call_soon_threadsafe = spy_cst

            # Simulate a GPIO edge event on that pin — the callback fires
            callback(first_pin)

            # call_soon_threadsafe should have been called once with queue.put_nowait("power")
            assert len(call_log) == 1
            func, args = call_log[0]
            # Bound methods create new objects on each attribute access in Python,
            # so compare by __self__ (the queue instance) and __name__.
            assert func.__self__ is queue
            assert func.__name__ == "put_nowait"
            assert args == ("power",)
