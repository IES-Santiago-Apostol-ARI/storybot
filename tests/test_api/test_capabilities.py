"""Tests for /api/capabilities endpoint (API-01)."""

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import State


def _reset_app_state(app):
    """Clear app.state so attributes from a prior TestClient session don't leak.

    Starlette's State object is backed by a dict on the app instance; exiting a
    TestClient context manager only triggers lifespan shutdown, not a state wipe.
    Without this reset, attributes set by an earlier test (e.g. story_generator)
    persist and cause false negatives in the "NOT set" tests.
    """
    app.state = State()


@pytest.fixture
def lifespan_env_ai_on(tmp_path, monkeypatch):
    """Lifespan env with AI forced ON (STORYBOT_AI=1), TESTING deleted.

    Disables TESTING so the full lifespan body runs (TTSPipeline wiring,
    content dir bootstrap). Overrides GENERATED_DIR to tmp so the sweeper
    does not touch the real filesystem.
    """
    generated = tmp_path / "generated"
    generated.mkdir()
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.setenv("STORYBOT_AI", "1")
    monkeypatch.setenv("STORYBOT_LIFESPAN_TEST", "1")
    from app.services.story_manager import StoryManager

    monkeypatch.setattr(StoryManager, "GENERATED_DIR", generated)
    return generated


@pytest.fixture
def lifespan_env_ai_off(tmp_path, monkeypatch):
    """Lifespan env with AI forced OFF (STORYBOT_AI=0), TESTING deleted."""
    generated = tmp_path / "generated"
    generated.mkdir()
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.setenv("STORYBOT_AI", "0")
    monkeypatch.setenv("STORYBOT_LIFESPAN_TEST", "1")
    from app.services.story_manager import StoryManager

    monkeypatch.setattr(StoryManager, "GENERATED_DIR", generated)
    return generated


class TestCapabilitiesEndpointAiOn:
    """API-01: GET /api/capabilities returns full profile when AI enabled."""

    def test_returns_full_profile_when_ai_enabled(self, lifespan_env_ai_on):
        from app.main import app

        _reset_app_state(app)
        with TestClient(app) as client:
            resp = client.get("/api/capabilities")
            # API-01: must return 200
            assert resp.status_code == 200, (
                "API-01: GET /api/capabilities must return 200 when AI enabled"
            )
            data = resp.json()
            # API-01: all five CapabilityProfile fields present
            assert set(data.keys()) == {
                "ai_enabled",
                "tts_available",
                "cover_gen",
                "printer",
                "reason",
            }, (
                "API-01: response keys must equal exactly "
                "{ai_enabled, tts_available, cover_gen, printer, reason}"
            )
            assert data["ai_enabled"] is True, (
                "API-01: ai_enabled must be True when STORYBOT_AI=1"
            )
            assert data["tts_available"] is True, (
                "API-01: tts_available must be True when STORYBOT_AI=1"
            )
            assert data["cover_gen"] is True, (
                "API-01: cover_gen must be True when STORYBOT_AI=1"
            )
            assert "printer" in data, (
                "API-01: printer key must be present in capabilities response"
            )
            assert data["reason"] == "env-override:forced-on", (
                "API-01: reason must be 'env-override:forced-on' when STORYBOT_AI=1"
            )


class TestCapabilitiesEndpointAiOff:
    """API-01: GET /api/capabilities returns full profile when AI disabled."""

    def test_returns_full_profile_when_ai_disabled(self, lifespan_env_ai_off):
        from app.main import app

        _reset_app_state(app)
        with TestClient(app) as client:
            resp = client.get("/api/capabilities")
            # API-01: must return 200
            assert resp.status_code == 200, (
                "API-01: GET /api/capabilities must return 200 when AI disabled"
            )
            data = resp.json()
            # API-01: all five CapabilityProfile fields present
            assert set(data.keys()) == {
                "ai_enabled",
                "tts_available",
                "cover_gen",
                "printer",
                "reason",
            }, (
                "API-01: response keys must equal exactly "
                "{ai_enabled, tts_available, cover_gen, printer, reason}"
            )
            assert data["ai_enabled"] is False, (
                "API-01: ai_enabled must be False when STORYBOT_AI=0"
            )
            assert data["tts_available"] is False, (
                "API-01: tts_available must be False when STORYBOT_AI=0"
            )
            assert data["cover_gen"] is False, (
                "API-01: cover_gen must be False when STORYBOT_AI=0"
            )
            assert "printer" in data, (
                "API-01: printer key must be present in capabilities response"
            )
            assert data["reason"] == "env-override:forced-off", (
                "API-01: reason must be 'env-override:forced-off' when STORYBOT_AI=0"
            )
