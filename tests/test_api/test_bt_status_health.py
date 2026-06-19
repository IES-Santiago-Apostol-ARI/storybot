"""Integration tests for Bluetooth status health surfacing (D-14).

Verifies that GET /api/bt/status correctly surfaces live BtMonitor state
when present in app.state, and falls back to backward-compatible defaults
when absent (e.g. during standard TestClient runs).
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from app.main import app


@pytest.fixture
def client(monkeypatch):
    """Create test client with lifespan context."""
    monkeypatch.setenv("STORYBOT_AI", "1")
    with TestClient(app) as c:
        yield c


class TestBtStatusHealth:
    """Verify D-14 status surface live wiring."""

    def test_status_without_monitor_is_backward_compatible(self, client):
        """
        When no BtMonitor is present in app.state (standard TESTING mode),
        the endpoint must still return a valid BtStatus with backward-compatible
        defaults and all existing fields.
        """
        # Ensure monitor is absent
        if hasattr(app.state, "bt_monitor"):
            del app.state.bt_monitor

        response = client.get("/api/bt/status")
        assert response.status_code == 200
        data = response.json()

        # New fields must have defaults
        assert "health_state" in data
        assert data["health_state"] == "unknown"
        assert "device_name" in data
        assert data["device_name"] is None

        # Existing fields MUST remain
        assert "name" in data
        assert "is_mock" in data
        assert "status" in data
        assert "platform" in data
        assert "adapter_present" in data
        assert "connected_mac" in data
        assert "sink" in data

    def test_status_with_monitor_reflects_live_state(self, client):
        """
        When a BtMonitor is present in app.state, /api/bt/status must overlay
        the live values from monitor.status() onto the response.
        """
        # Create a stub monitor
        mock_monitor = MagicMock()
        mock_monitor.status.return_value = {
            "sink": "bt",
            "health_state": "connected",
            "device_mac": "AA:BB:CC:00:11:22",
            "device_name": "Mock JBL",
        }
        
        # Inject into app.state
        app.state.bt_monitor = mock_monitor

        response = client.get("/api/bt/status")
        assert response.status_code == 200
        data = response.json()

        # Verify monitor values are surfaced
        assert data["health_state"] == "connected"
        assert data["device_name"] == "Mock JBL"
        assert data["sink"] == "bt"
        assert data["connected_mac"] == "AA:BB:CC:00:11:22"

        # Verify base fields are still present
        assert "platform" in data
        assert "adapter_present" in data

        # Cleanup for other tests
        del app.state.bt_monitor
