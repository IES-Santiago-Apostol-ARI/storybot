"""Tarea 3: a lifespan failure in detect_hardware must not block boot.

A single peripheral failure (corrupt config, pyscard import in
RealNFCService._start_monitor) must degrade, not kill, the whole robot:
NFC, printing, LED and the story library must survive.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def lifespan_env(tmp_path, monkeypatch):
    """Point GENERATED_DIR at a tmp dir, disable TESTING gate so lifespan body runs."""
    generated = tmp_path / "generated"
    generated.mkdir()
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.setenv("STORYBOT_LIFESPAN_TEST", "1")
    from app.services.story_manager import StoryManager

    monkeypatch.setattr(StoryManager, "GENERATED_DIR", generated)
    return generated


@pytest.fixture
def broken_detect_hardware(monkeypatch):
    """Patch HardwareManager.detect_hardware to raise, simulating a peripheral fault."""
    from app.services.hardware_manager import HardwareManager

    async def _failing_detect(self, ai_enabled: bool = False):
        raise RuntimeError("detect_hardware failed")

    monkeypatch.setattr(HardwareManager, "detect_hardware", _failing_detect)


class TestDetectHardwareFailureIsolation:
    def test_detect_hardware_failure_does_not_block_boot(
        self, lifespan_env, broken_detect_hardware, capsys
    ):
        """A raising detect_hardware must not abort startup."""
        from app.main import app

        with TestClient(app) as client:
            state = client.app.state
            assert hasattr(state, "hardware"), (
                "app.state.hardware must exist even when detect_hardware raises"
            )
            assert hasattr(state, "config"), (
                "app.state.config must exist even when detect_hardware raises"
            )
            assert hasattr(state, "story_manager"), (
                "app.state.story_manager must exist even when detect_hardware raises"
            )

        captured = capsys.readouterr()
        assert "hardware_detect_failed" in captured.err, (
            "lifespan must log a hardware_detect_failed JSON event to stderr when "
            "detect_hardware raises"
        )

    def test_routes_still_serve_after_detect_failure(
        self, lifespan_env, broken_detect_hardware
    ):
        """The story library must keep serving with a broken detect_hardware."""
        from app.main import app

        with TestClient(app) as client:
            resp = client.get("/api/stories")
            assert (
                resp.status_code == 200
            ), "GET /api/stories must return 200 even when detect_hardware raises"
