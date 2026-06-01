"""Tests for OTA update API endpoints — check, apply, version."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(monkeypatch):
    """Create test client with lifespan context.

    Force AI enabled so the app boots fully.
    """
    monkeypatch.setenv("STORYBOT_AI", "1")
    with TestClient(app) as c:
        yield c


def _mock_update_manager(
    check_return=None,
    apply_events=None,
    version_return=None,
    check_side_effect=None,
):
    """Create a mock UpdateManager with configurable behavior."""
    mgr = AsyncMock()
    mgr.is_mock = True

    # check_update: async method returning dict
    mgr.check_update = AsyncMock(
        return_value=check_return
        if check_return is not None
        else {
            "update_available": False,
            "local_commit": "abc1234",
            "remote_commit": "abc1234",
        }
    )
    if check_side_effect:
        mgr.check_update = AsyncMock(side_effect=check_side_effect)

    # apply_update: async generator yielding events
    async def _default_apply():
        for event in apply_events or [
            {"stage": "fetching", "done": False},
            {"stage": "restarting", "done": True},
        ]:
            yield event

    mgr.apply_update = _default_apply

    # get_version: async method returning dict
    mgr.get_version = AsyncMock(
        return_value=version_return
        if version_return is not None
        else {"version": "v1.0-5-gabc", "commit": "abc1234"}
    )

    return mgr


@patch("app.routers.updates.create_update_manager")
class TestCheckEndpoint:
    """Test GET /api/updates/check endpoint."""

    def test_check_returns_200_with_update_info(self, mock_factory, client):
        """Check returns 200 with update_available and commit info."""
        mock_factory.return_value = _mock_update_manager(
            check_return={
                "update_available": True,
                "local_commit": "abc1234",
                "remote_commit": "def5678",
            }
        )
        response = client.get("/api/updates/check")
        assert response.status_code == 200
        data = response.json()
        assert data["update_available"] is True
        assert data["local_commit"] == "abc1234"
        assert data["remote_commit"] == "def5678"

    def test_check_returns_false_on_fetch_error(self, mock_factory, client):
        """Check returns 200 with update_available false on error."""
        mock_factory.return_value = _mock_update_manager(
            check_return={
                "update_available": False,
                "local_commit": "unknown",
                "remote_commit": "unknown",
                "error": "fetch failed",
            }
        )
        response = client.get("/api/updates/check")
        assert response.status_code == 200
        data = response.json()
        assert data["update_available"] is False
        assert data["error"] == "fetch failed"


@patch("app.routers.updates.create_update_manager")
class TestApplyEndpoint:
    """Test POST /api/updates/apply endpoint."""

    def test_apply_returns_sse_stream(self, mock_factory, client):
        """Apply returns SSE text/event-stream with stage events."""
        mock_factory.return_value = _mock_update_manager(
            apply_events=[
                {"stage": "fetching", "done": False},
                {"stage": "restarting", "done": True},
            ]
        )
        response = client.post("/api/updates/apply")
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        body = response.text
        assert "data:" in body
        assert "fetching" in body
        assert "restarting" in body

    def test_apply_streams_error_on_failure(self, mock_factory, client):
        """Apply includes error event when manager yields error."""
        mock_factory.return_value = _mock_update_manager(
            apply_events=[
                {"stage": "error", "error": "fetch failed"},
            ]
        )
        response = client.post("/api/updates/apply")
        assert response.status_code == 200
        body = response.text
        assert "error" in body
        assert "fetch failed" in body


@patch("app.routers.updates.create_update_manager")
class TestVersionEndpoint:
    """Test GET /api/updates/version endpoint."""

    def test_version_returns_200(self, mock_factory, client):
        """Version returns 200 with version and commit strings."""
        mock_factory.return_value = _mock_update_manager(
            version_return={"version": "v1.0-5-gabc", "commit": "abc1234"}
        )
        response = client.get("/api/updates/version")
        assert response.status_code == 200
        data = response.json()
        assert data["version"] == "v1.0-5-gabc"
        assert data["commit"] == "abc1234"


class TestUpdatesRouterRegistration:
    """Test that updates router is registered and accessible."""

    def test_check_endpoint_exists(self, client):
        """GET /api/updates/check is registered (not 404)."""
        response = client.get("/api/updates/check")
        assert response.status_code != 404

    def test_version_endpoint_exists(self, client):
        """GET /api/updates/version is registered (not 404)."""
        response = client.get("/api/updates/version")
        assert response.status_code != 404

    def test_apply_endpoint_exists(self, client):
        """POST /api/updates/apply is registered (not 404)."""
        response = client.post("/api/updates/apply")
        assert response.status_code != 404
