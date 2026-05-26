"""Integration tests for Phase 17 lifespan capability wiring.

CAP-01..04, D-07/D-09/D-12/D-17.
Plan 17-04: lifespan probes capability at startup and conditionally branches
AI service initialization on the resolved ai_enabled value.
"""

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


class TestLifespanWithAiEnabled:
    """D-17 ai-enabled branch: AI services are initialized on app.state."""

    def test_app_state_ai_enabled_is_true(self, lifespan_env_ai_on):
        from app.main import app

        _reset_app_state(app)
        with TestClient(app) as client:
            assert hasattr(
                client.app.state, "ai_enabled"
            ), "Plan 17-04: CAP-03 requires literal app.state.ai_enabled attribute"
            assert (
                client.app.state.ai_enabled is True
            ), "Plan 17-04: STORYBOT_AI=1 must set app.state.ai_enabled to True"

    def test_app_state_capability_exists(self, lifespan_env_ai_on):
        from app.main import app
        from app.models.capability import CapabilityProfile

        _reset_app_state(app)
        with TestClient(app) as client:
            assert hasattr(
                client.app.state, "capability"
            ), "Plan 17-04: app.state.capability must be set after lifespan startup"
            profile = client.app.state.capability
            assert isinstance(
                profile, CapabilityProfile
            ), "Plan 17-04: app.state.capability must be a CapabilityProfile instance"
            assert (
                profile.ai_enabled is True
            ), "Plan 17-04: capability.ai_enabled must be True when STORYBOT_AI=1"
            assert (
                profile.reason == "env-override:forced-on"
            ), "Plan 17-04: capability.reason must be 'env-override:forced-on'"

    def test_story_generator_is_set(self, lifespan_env_ai_on):
        from app.main import app

        _reset_app_state(app)
        with TestClient(app) as client:
            assert hasattr(
                client.app.state, "story_generator"
            ), "Plan 17-04: app.state.story_generator must exist when ai_enabled=True"
            assert (
                client.app.state.story_generator is not None
            ), "Plan 17-04: story_generator must not be None when ai_enabled=True"

    def test_swap_orchestrator_is_set(self, lifespan_env_ai_on):
        from app.main import app

        _reset_app_state(app)
        with TestClient(app) as client:
            assert hasattr(
                client.app.state, "swap_orchestrator"
            ), "Plan 17-04: swap_orchestrator must exist when ai_enabled=True"
            assert (
                client.app.state.swap_orchestrator is not None
            ), "Plan 17-04: swap_orchestrator must not be None when ai_enabled=True"

    def test_tts_pipeline_is_set(self, lifespan_env_ai_on):
        from app.main import app

        _reset_app_state(app)
        with TestClient(app) as client:
            assert hasattr(client.app.state, "tts_pipeline"), (
                "Plan 17-04: app.state.tts_pipeline must exist when ai_enabled=True "
                "and TESTING is not set"
            )
            assert (
                client.app.state.tts_pipeline is not None
            ), "Plan 17-04: tts_pipeline must not be None when ai_enabled=True"

    def test_printer_field_reflects_actual_init(self, lifespan_env_ai_on):
        from app.main import app

        _reset_app_state(app)
        with TestClient(app) as client:
            # D-08/D-13: capability.printer is overwritten from the probe default
            # (False) to reflect actual printer init result.
            profile = client.app.state.capability
            printer = getattr(client.app.state, "printer", None)
            # In test env (TESTING deleted), factory returns MockPrinterService.
            # is_mock=True → capability.printer should be False (no real printer).
            expected = printer is not None and not getattr(printer, "is_mock", True)
            assert profile.printer == expected, (
                f"Plan 17-04 D-08: capability.printer ({profile.printer}) must match "
                f"actual printer init ({expected})"
            )

    def test_hardware_status_contains_tts_key(self, lifespan_env_ai_on):
        from app.main import app

        _reset_app_state(app)
        with TestClient(app) as client:
            resp = client.get("/api/system/status")
            data = resp.json()
            assert "tts" in data.get("hardware", {}), (
                "Plan 17-04 D-17: hardware status must contain 'tts' key when "
                "ai_enabled=True"
            )


class TestLifespanWithAiDisabled:
    """D-17 ai-disabled branch: AI services are NOT set on app.state (D-09)."""

    def test_app_state_ai_enabled_is_false(self, lifespan_env_ai_off):
        from app.main import app

        _reset_app_state(app)
        with TestClient(app) as client:
            assert hasattr(
                client.app.state, "ai_enabled"
            ), "Plan 17-04: CAP-03 requires literal app.state.ai_enabled attribute"
            assert (
                client.app.state.ai_enabled is False
            ), "Plan 17-04: STORYBOT_AI=0 must set app.state.ai_enabled to False"

    def test_app_state_capability_exists_with_disabled_flags(self, lifespan_env_ai_off):
        from app.main import app

        _reset_app_state(app)
        with TestClient(app) as client:
            profile = client.app.state.capability
            assert (
                profile.ai_enabled is False
            ), "Plan 17-04: capability.ai_enabled must be False when STORYBOT_AI=0"
            assert (
                profile.tts_available is False
            ), "Plan 17-04: tts_available must be False when ai_enabled=False"
            assert (
                profile.cover_gen is False
            ), "Plan 17-04: capability.cover_gen must be False when ai_enabled=False"
            assert (
                profile.reason == "env-override:forced-off"
            ), "Plan 17-04: capability.reason must be 'env-override:forced-off'"

    def test_story_generator_not_set(self, lifespan_env_ai_off):
        from app.main import app

        _reset_app_state(app)
        with TestClient(app) as client:
            assert not hasattr(client.app.state, "story_generator"), (
                "Plan 17-04 CAP-04: app.state.story_generator must NOT exist when "
                "ai_enabled=False — no stub, no None (D-09)"
            )

    def test_swap_orchestrator_not_set(self, lifespan_env_ai_off):
        from app.main import app

        _reset_app_state(app)
        with TestClient(app) as client:
            assert not hasattr(client.app.state, "swap_orchestrator"), (
                "Plan 17-04 CAP-04: app.state.swap_orchestrator must NOT exist when "
                "ai_enabled=False — no stub, no None (D-09)"
            )

    def test_tts_pipeline_not_set(self, lifespan_env_ai_off):
        from app.main import app

        _reset_app_state(app)
        with TestClient(app) as client:
            assert not hasattr(client.app.state, "tts_pipeline"), (
                "Plan 17-04 CAP-04: app.state.tts_pipeline must NOT exist when "
                "ai_enabled=False — no stub, no None (D-09)"
            )

    def test_printer_still_set_independent_of_ai(self, lifespan_env_ai_off):
        from app.main import app

        _reset_app_state(app)
        with TestClient(app) as client:
            assert hasattr(
                client.app.state, "printer"
            ), "Plan 17-04 D-08: printer must be set regardless of ai_enabled"

    def test_hardware_status_omits_tts_key(self, lifespan_env_ai_off):
        from app.main import app

        _reset_app_state(app)
        with TestClient(app) as client:
            resp = client.get("/api/system/status")
            data = resp.json()
            assert "tts" not in data.get("hardware", {}), (
                "Plan 17-04 D-16/D-17: hardware status must NOT contain 'tts' key "
                "when ai_enabled=False"
            )
