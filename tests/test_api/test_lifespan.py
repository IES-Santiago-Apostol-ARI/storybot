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
