"""Tests for GPIO button service infrastructure.

Verifies the HardwareService Mock/Real pattern, factory branching, mock
trigger seam, and lifespan lifecycle (create + clean cancel).
"""

import os

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
        import asyncio

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
