"""Tests for platform field on GET /api/system/status (Phase 26-03, D-07).

RESEARCH Open Question 3: detect_platform() lands as an informational
``platform`` field on the system status response. Informational only —
no behavior is gated on it.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(monkeypatch):
    """Create test client with lifespan context (mirrors test_system.py)."""
    monkeypatch.setenv("STORYBOT_AI", "1")
    with TestClient(app) as c:
        yield c


class TestSystemStatusPlatform:
    """Test that GET /api/system/status surfaces a platform field."""

    def test_status_includes_platform_key(self, client):
        """GET /api/system/status response has a platform field."""
        response = client.get("/api/system/status")
        assert response.status_code == 200
        data = response.json()
        assert "platform" in data, "platform field missing from system status"

    def test_status_platform_value_is_valid(self, client):
        """platform is one of jetson|rpi|generic (D-08/D-09)."""
        response = client.get("/api/system/status")
        data = response.json()
        assert data["platform"] in {"jetson", "rpi", "generic"}

    def test_status_still_has_existing_fields(self, client):
        """Adding platform does not remove hardware/uptime_seconds/version."""
        response = client.get("/api/system/status")
        data = response.json()
        assert "hardware" in data
        assert "uptime_seconds" in data
        assert "version" in data


class TestSystemRescanPlatform:
    """Test that POST /api/system/rescan also surfaces platform (D-07).

    Both get_system_status and rescan_hardware build SystemStatus(**status_dict)
    identically, so platform must be injected in both.
    """

    def test_rescan_includes_platform_key(self, client):
        """POST /api/system/rescan response has a platform field."""
        response = client.post("/api/system/rescan")
        assert response.status_code == 200
        data = response.json()
        assert "platform" in data, "platform field missing from rescan status"

    def test_rescan_platform_value_is_valid(self, client):
        """platform on rescan is one of jetson|rpi|generic."""
        response = client.post("/api/system/rescan")
        data = response.json()
        assert data["platform"] in {"jetson", "rpi", "generic"}
