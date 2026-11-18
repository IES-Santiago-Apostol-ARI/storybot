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


class TestLastCoverOnEnded:
    """Image button source: 'ended' on a recorded story refreshes last-cover."""

    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        from types import SimpleNamespace

        from app.dependencies import get_story_manager

        story = SimpleNamespace(
            id="rec-1", title="t", led_color=None, cover_image="cover.jpg"
        )
        sm = SimpleNamespace(
            get_story=lambda _id: story, get_story_by_nfc=lambda _u: None
        )
        app.dependency_overrides[get_story_manager] = lambda: sm
        with TestClient(app) as c:
            monkeypatch.chdir(tmp_path)  # route resolves content/ relative to cwd
            yield c, story, tmp_path
        app.dependency_overrides.pop(get_story_manager, None)

    def _post(self, c, state):
        return c.post(
            "/api/system/led/state", json={"state": state, "story_id": "rec-1"}
        )

    def test_ended_copies_own_cover(self, client):
        c, _story, tmp = client
        (tmp / "content/stories/rec-1").mkdir(parents=True)
        (tmp / "content/stories/rec-1/cover.jpg").write_bytes(b"OWN")

        assert self._post(c, "ended").status_code == 200
        assert (tmp / "last-cover").read_bytes() == b"OWN"

    def test_ended_falls_back_to_sticker(self, client):
        c, story, tmp = client
        story.cover_image = None
        (tmp / "content/generated/rec-1").mkdir(parents=True)
        (tmp / "content/generated/rec-1/cover-print.png").write_bytes(b"STICKER")

        assert self._post(c, "ended").status_code == 200
        assert (tmp / "last-cover").read_bytes() == b"STICKER"

    def test_playback_does_not_copy(self, client):
        c, _story, tmp = client
        (tmp / "content/stories/rec-1").mkdir(parents=True)
        (tmp / "content/stories/rec-1/cover.jpg").write_bytes(b"OWN")

        assert self._post(c, "playback").status_code == 200
        assert not (tmp / "last-cover").exists()


class TestLastCoverOnInterrupted:
    """A recorded story abandoned mid-playback (kiosk drops to 'idle' with no
    story id) also refreshes last-cover, so the image button can print it
    without listening to the whole story."""

    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        from types import SimpleNamespace

        from app.dependencies import get_story_manager

        story = SimpleNamespace(
            id="rec-1", title="t", led_color=None, cover_image="cover.jpg"
        )
        sm = SimpleNamespace(
            get_story=lambda _id: story, get_story_by_nfc=lambda _u: None
        )
        app.dependency_overrides[get_story_manager] = lambda: sm
        with TestClient(app) as c:
            monkeypatch.chdir(tmp_path)
            (tmp_path / "content/stories/rec-1").mkdir(parents=True)
            (tmp_path / "content/stories/rec-1/cover.jpg").write_bytes(b"OWN")
            yield c, tmp_path
        app.dependency_overrides.pop(get_story_manager, None)

    def test_idle_after_playback_copies_cover(self, client):
        c, tmp = client
        c.post(
            "/api/system/led/state", json={"state": "playback", "story_id": "rec-1"}
        )
        assert c.post("/api/system/led/state", json={"state": "idle"}).status_code == 200
        assert (tmp / "last-cover").read_bytes() == b"OWN"

    def test_idle_without_playback_copies_nothing(self, client):
        c, tmp = client
        app.state.playback = None
        assert c.post("/api/system/led/state", json={"state": "idle"}).status_code == 200
        assert not (tmp / "last-cover").exists()
