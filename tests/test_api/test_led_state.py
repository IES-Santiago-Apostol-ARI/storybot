"""Tests for /api/system/led/state route.

These tests verify the new additive endpoint that drives the LED engine
into named modes (idle, playback, thinking, ended, error, etc.) with
semantic parameters. The route is additive — the original /api/system/led
endpoint remains unchanged.

Requirements covered: LED-10..LED-25 via route input validation and
semantic state transitions.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


class TestLEDStateRoute:
    """Phase 33 /led/state route tests (RED until plan 04)."""

    @pytest.fixture
    def client(self, monkeypatch):
        """Test client with real lifespan (engine starts over MockLEDService)."""
        monkeypatch.setenv("STORYBOT_AI", "1")
        with TestClient(app) as c:
            yield c

    def test_led_state_accepts_known_states(self, client):
        """POST /led/state with known states returns 200."""
        for state in ["idle", "ended", "thinking"]:
            response = client.post(
                "/api/system/led/state",
                json={"state": state},
            )
            assert response.status_code == 200, f"State '{state}' should be accepted"
            data = response.json()
            assert "state" in data
            assert data["state"] == state

    def test_led_state_rejects_unknown_state(self, client):
        """LED-24: Unknown states rejected with 422 (ASVS V5).

        Default-deny input validation — child-safety gate.
        """
        response = client.post(
            "/api/system/led/state",
            json={"state": "party_strobe"},
        )
        assert response.status_code == 422, "Unknown state should be rejected"

    def test_led_state_playback_resolves_color(self, client):
        """LED-10: Playback mode resolves story color via story_manager.

        POST /led/state with playback + story_id → backend resolves led_color.
        """
        response = client.post(
            "/api/system/led/state",
            json={"state": "playback", "story_id": "test-story"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "state" in data
        assert data["state"] == "playback"
        # Should return the resolved color
        assert "rgb" in data or "color" in data

    def test_led_state_503_when_engine_missing(self, client, monkeypatch):
        """LED-09: /led/state returns 503 when animator is not initialized."""
        monkeypatch.setattr(app.state, "led_animator", None)
        response = client.post(
            "/api/system/led/state",
            json={"state": "idle"},
        )
        assert response.status_code == 503
        assert "LED engine not available" in response.text

    def test_led_endpoint_not_overloaded(self, client):
        """D-02: Original /api/system/led still works unchanged.

        The new /led/state is additive, NOT an overload of /led.
        """
        response = client.post(
            "/api/system/led",
            json={"color": "#FF0000"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["color"] == "#FF0000"
        assert data["rgb"] == [255, 0, 0]
