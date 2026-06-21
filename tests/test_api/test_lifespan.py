"""Wave 0 RED stubs for FastAPI lifespan attachments (D-13, D-18).

Plan 16-01 turns these GREEN by:
  - attaching app.state.swap_orchestrator (already done by Phase 15 — regression-asserted here)
  - attaching app.state.printer = create_printer_service()  (NEW in 16-01)
  - calling sweep_generated(...) at startup against StoryManager.GENERATED_DIR  (NEW in 16-01)

The lifespan smoke is exercised via FastAPI TestClient context-manager — entering the
`with TestClient(app) as c:` block triggers startup; exiting triggers shutdown.
"""

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


def _seed_stale_dir(generated: Path, story_id: str, age_seconds: float) -> Path:
    d = generated / story_id
    (d / "audio").mkdir(parents=True)
    sj = d / "story.json"
    sj.write_text(
        json.dumps(
            {
                "id": story_id,
                "text": "x",
                "parameters": [],
                "created_at": "2026-01-01T00:00:00Z",
            }
        )
    )
    mtime = time.time() - age_seconds
    os.utime(sj, (mtime, mtime))
    os.utime(d, (mtime, mtime))
    return d


def _seed_fresh_dir(generated: Path, story_id: str) -> Path:
    d = generated / story_id
    (d / "audio").mkdir(parents=True)
    sj = d / "story.json"
    sj.write_text(
        json.dumps(
            {
                "id": story_id,
                "text": "x",
                "parameters": [],
                "created_at": "2026-04-30T00:00:00Z",
            }
        )
    )
    return d


@pytest.fixture
def lifespan_env(tmp_path, monkeypatch):
    """Point GENERATED_DIR at a tmp dir, disable TESTING gate so lifespan body runs."""
    generated = tmp_path / "generated"
    generated.mkdir()
    # Disable TESTING so the lifespan actually invokes the sweeper / printer factory.
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.setenv("STORYBOT_LIFESPAN_TEST", "1")
    # Force AI enabled so Phase 16 tests see swap_orchestrator / tts_pipeline.
    monkeypatch.setenv("STORYBOT_AI", "1")
    from app.services.story_manager import StoryManager

    monkeypatch.setattr(StoryManager, "GENERATED_DIR", generated)
    return generated


class TestLifespanStateAttachment:
    def test_swap_orchestrator_attached_after_startup(self, lifespan_env):
        from app.main import app

        with TestClient(app) as client:
            assert hasattr(
                client.app.state, "swap_orchestrator"
            ), "Phase 15 regression: app.state.swap_orchestrator must be set by lifespan"

    def test_printer_attached_after_startup(self, lifespan_env):
        from app.main import app

        with TestClient(app) as client:
            assert hasattr(
                client.app.state, "printer"
            ), "Plan 16-01 RED: app.state.printer = create_printer_service() must be set by lifespan"


class TestLifespanSweeperInvocation:
    def test_stale_dir_removed_at_startup(self, lifespan_env, capsys):
        generated = lifespan_env
        stale = _seed_stale_dir(generated, "stale-uuid", age_seconds=8 * 86400)
        fresh = _seed_fresh_dir(generated, "fresh-uuid")

        from app.main import app

        with TestClient(app):
            pass  # startup runs sweeper; shutdown is a no-op for this assertion

        assert (
            not stale.exists()
        ), "Plan 16-01 RED: lifespan must call sweep_generated against GENERATED_DIR"
        assert fresh.exists(), "Sweeper must NOT remove fresh dirs"

    def test_sweep_complete_event_emitted(self, lifespan_env, capsys):
        generated = lifespan_env
        _seed_stale_dir(generated, "stale-uuid", age_seconds=8 * 86400)

        from app.main import app

        with TestClient(app):
            pass

        captured = capsys.readouterr()
        # The sweeper logs a JSON sweep_complete event to stderr at the end.
        assert (
            "sweep_complete" in captured.err
        ), "Plan 16-01 RED: lifespan sweeper must log sweep_complete JSON to stderr"


class TestLifespanLEDEngineWiring:
    """Plan 33-06: lifespan feeds health status + arms the boot sweep (D-05/D-14/LED-21/LED-18)."""

    def test_boot_sweep_armed_at_startup(self, lifespan_env):
        """LED-18 / D-10: the lifespan arms the engine-internal boot sweep over the mock."""
        import asyncio

        from app.main import app

        with TestClient(app) as client:
            animator = client.app.state.led_animator
            assert animator is not None, "LedAnimator must be constructed unconditionally"
            # The boot sweep is armed via set_mode("boot"); _boot_started_at must be
            # set (engine-internal one-shot, D-10). Let the loop tick once so the
            # engine can advance its boot state if needed.
            async def _tick():
                await animator.tick_once()

            asyncio.run(_tick())
            assert (
                animator._boot_started_at is not None
            ), "Plan 33-06 RED: lifespan must arm the boot sweep via set_mode('boot')"

    def test_health_status_fed_at_startup(self, lifespan_env, monkeypatch):
        """LED-21 / D-05: lifespan derives service-down flag from HardwareManager and feeds set_health."""
        from app.main import app

        # Spy on set_health to prove the lifespan actually calls it (not just the
        # default _health_down=False sentinel). The spy delegates to the real impl.
        from app.services.led_animator import LedAnimator

        calls: list[bool] = []
        real_set_health = LedAnimator.set_health

        def _spy(self, down: bool):
            calls.append(down)
            return real_set_health(self, down)

        monkeypatch.setattr(LedAnimator, "set_health", _spy)

        with TestClient(app) as client:
            animator = client.app.state.led_animator
            assert animator is not None

        assert calls, (
            "Plan 33-06 RED: lifespan must call set_health(down=...) derived from "
            "HardwareManager status at startup (no call observed)"
        )
        # The fed value must be a concrete bool derived from real status (not a
        # sentinel). The exact value depends on which mock services report error
        # in this CI environment; what matters is the wiring fired.
        assert isinstance(calls[-1], bool)

    def test_health_down_when_service_in_error(self, lifespan_env):
        """LED-21 / D-05: a hardware service in error status drives _health_down True."""
        from unittest.mock import AsyncMock

        from app.main import app
        from app.models.system import HardwareState

        error_status = {
            "hardware": {
                "nfc": HardwareState(
                    name="nfc", is_mock=True, status="error", error_message="x"
                ).dict()
            },
            "uptime_seconds": 1.0,
            "version": "0.1.0",
        }

        with TestClient(app) as client:
            animator = client.app.state.led_animator
            hardware = client.app.state.hardware

            # Force one service to report an error status and re-feed the engine.
            hardware.get_status = AsyncMock(return_value=error_status)

            # Re-derive + feed (mirrors what the lifespan wiring does).
            status = hardware.get_status.return_value
            any_down = any(
                svc.get("status") == "error"
                for svc in status.get("hardware", {}).values()
            )
            animator.set_health(down=any_down)
            assert animator._health_down is True, (
                "A service in error status must drive _health_down True (D-05/LED-21)"
            )
