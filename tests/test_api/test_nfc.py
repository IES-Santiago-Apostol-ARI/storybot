"""Tests for NFC API endpoints."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_story_manager
from app.routers.nfc import router
from app.services.hardware_manager import HardwareManager
from app.services.nfc_handler import MockNFCService
from app.services.story_manager import StoryManager


@pytest.fixture
def mock_nfc_service():
    """Create a mock NFC service."""
    return MockNFCService()


@pytest.fixture
def mock_story_manager():
    """Create a mock story manager for card lookups."""
    manager = MagicMock(spec=StoryManager)
    manager.get_card.return_value = None
    return manager


@pytest.fixture
def hardware_with_nfc(mock_nfc_service):
    """Create hardware manager with NFC service registered."""
    hardware = HardwareManager()
    hardware.register_service("nfc", mock_nfc_service)
    return hardware


@pytest.fixture
def hardware_without_nfc():
    """Create hardware manager without NFC service."""
    return HardwareManager()


@pytest.fixture
def app_with_nfc(hardware_with_nfc, mock_story_manager):
    """Create test app with NFC service."""
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.state.hardware = hardware_with_nfc
    test_app.state.story_manager = mock_story_manager

    async def override_sm():
        return mock_story_manager

    test_app.dependency_overrides[get_story_manager] = override_sm
    return test_app


@pytest.fixture
def app_without_nfc(hardware_without_nfc, mock_story_manager):
    """Create test app without NFC service."""
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.state.hardware = hardware_without_nfc
    test_app.state.story_manager = mock_story_manager

    async def override_sm():
        return mock_story_manager

    test_app.dependency_overrides[get_story_manager] = override_sm
    return test_app


class TestNFCStatusEndpoint:
    """Test GET /api/nfc/status endpoint."""

    def test_nfc_status_returns_service_state(self, app_with_nfc):
        """GET /api/nfc/status returns NFC service status."""
        with TestClient(app_with_nfc) as client:
            response = client.get("/api/nfc/status")
            assert response.status_code == 200
            data = response.json()
            assert data["name"] == "nfc"
            assert "is_mock" in data
            assert "status" in data

    def test_nfc_status_shows_mock_flag(self, app_with_nfc):
        """GET /api/nfc/status correctly reports mock status."""
        with TestClient(app_with_nfc) as client:
            response = client.get("/api/nfc/status")
            data = response.json()
            assert data["is_mock"] is True  # MockNFCService

    def test_nfc_status_without_service(self, app_without_nfc):
        """GET /api/nfc/status handles missing service gracefully."""
        with TestClient(app_without_nfc) as client:
            response = client.get("/api/nfc/status")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "not_connected"
            assert data["error_message"] == "NFC service not registered"
            assert data["is_mock"] is True


class TestNFCReadEndpoint:
    """Test GET /api/nfc/read SSE endpoint."""

    def test_nfc_read_without_service_returns_error_event(self, app_without_nfc):
        """GET /api/nfc/read returns error event when service missing."""
        client = TestClient(app_without_nfc)
        with client.stream("GET", "/api/nfc/read") as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")
            content = response.read().decode()
            assert "error" in content
            assert "NFC service not available" in content


class TestNFCReadEventStream:
    """Test NFC read event stream logic directly."""

    @pytest.mark.asyncio
    async def test_event_stream_yields_error_without_service(self):
        """Event stream yields error when NFC service not available."""
        from app.routers.nfc import read_nfc_cards

        mock_hardware = MagicMock()
        mock_hardware._services = {}
        mock_story_manager = MagicMock()

        response = await read_nfc_cards(
            hardware=mock_hardware, story_manager=mock_story_manager
        )

        # Get the generator from the response
        event_gen = response.body_iterator

        # Get first event (dict with 'event' and 'data' keys)
        event = await event_gen.__anext__()
        assert event["event"] == "error"
        assert "NFC service not available" in event["data"]

    @pytest.mark.asyncio
    async def test_event_stream_starts_polling(self):
        """Event stream starts NFC polling when service available."""
        from app.routers.nfc import read_nfc_cards

        mock_nfc = AsyncMock()
        mock_nfc.start_polling = AsyncMock()
        mock_nfc.stop_polling = AsyncMock()

        mock_hardware = MagicMock()
        mock_hardware._services = {"nfc": mock_nfc}
        mock_story_manager = MagicMock()

        response = await read_nfc_cards(
            hardware=mock_hardware, story_manager=mock_story_manager
        )
        event_gen = response.body_iterator

        # The generator should have started - trigger it
        # We need to cancel it since it's an infinite loop
        task = asyncio.create_task(event_gen.__anext__())

        # Give it time to start
        await asyncio.sleep(0.1)

        # Cancel and cleanup
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Verify polling was started
        mock_nfc.start_polling.assert_called_once()

    @pytest.mark.asyncio
    async def test_event_stream_yields_card_data(self):
        """Event stream yields card UID when card tapped."""
        import json

        from app.routers.nfc import read_nfc_cards

        callback_holder = {}

        async def mock_start_polling(callback):
            callback_holder["cb"] = callback

        mock_nfc = MagicMock()
        mock_nfc.start_polling = mock_start_polling
        mock_nfc.stop_polling = AsyncMock()

        mock_hardware = MagicMock()
        mock_hardware._services = {"nfc": mock_nfc}
        mock_story_manager = MagicMock()
        mock_story_manager.get_card.return_value = None

        response = await read_nfc_cards(
            hardware=mock_hardware, story_manager=mock_story_manager
        )
        event_gen = response.body_iterator

        # Start consuming the generator
        async def get_event():
            return await event_gen.__anext__()

        task = asyncio.create_task(get_event())
        await asyncio.sleep(0.1)  # Let polling start

        # Simulate card tap
        test_uid = "04:A3:5B:C2:D4:30"
        callback_holder["cb"](test_uid)

        # Get the event (dict with 'event' and 'data' keys)
        event = await asyncio.wait_for(task, timeout=1.0)

        # Verify event contains UID
        assert event["event"] == "card"
        assert test_uid in event["data"]

        # Cleanup
        await mock_nfc.stop_polling()
