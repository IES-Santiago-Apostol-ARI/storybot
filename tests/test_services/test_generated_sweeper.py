"""Wave 0 RED stubs for app.services.generated_sweeper (D-13).

These tests fail today because app.services.generated_sweeper does not exist.
Plan 16-01 makes them GREEN.
"""

import json
import time
from pathlib import Path

import pytest

# This import will FAIL today — RED.
pytest.importorskip("app.services.generated_sweeper", reason="Wave 0 RED stub: implemented in Plan 16-01")

from app.services.generated_sweeper import (  # noqa: E402
    MAX_AGE_SECONDS,
    sweep_generated,
)
from app.services.story_manager import StoryManager  # noqa: E402


@pytest.fixture
def story_manager_with_generated(tmp_path):
    generated = tmp_path / "generated"
    generated.mkdir()
    sm = StoryManager()
    sm.GENERATED_DIR = generated
    return sm, generated


def _seed_dir(parent: Path, story_id: str, age_seconds: float, now: float) -> Path:
    d = parent / story_id
    d.mkdir()
    sj = d / "story.json"
    sj.write_text(json.dumps({"id": story_id, "text": "x", "parameters": [], "created_at": "2026-01-01T00:00:00Z"}))
    mtime = now - age_seconds
    import os
    os.utime(sj, (mtime, mtime))
    os.utime(d, (mtime, mtime))
    return d


class TestSweepGenerated:
    def test_max_age_constant_is_seven_days(self):
        assert MAX_AGE_SECONDS == 7 * 86400

    def test_removes_stale_keeps_fresh(self, story_manager_with_generated):
        sm, generated = story_manager_with_generated
        now = time.time()
        stale = _seed_dir(generated, "stale-uuid", age_seconds=8 * 86400, now=now)
        fresh = _seed_dir(generated, "fresh-uuid", age_seconds=86400, now=now)
        removed = sweep_generated(story_manager=sm, generated_dir=generated, now_seconds=now)
        assert removed == 1
        assert not stale.exists()
        assert fresh.exists()

    def test_emits_stderr_json_per_removal(self, story_manager_with_generated, capsys):
        sm, generated = story_manager_with_generated
        now = time.time()
        _seed_dir(generated, "stale-uuid", age_seconds=8 * 86400, now=now)
        sweep_generated(story_manager=sm, generated_dir=generated, now_seconds=now)
        captured = capsys.readouterr()
        events = [json.loads(line) for line in captured.err.strip().split("\n") if line.strip()]
        kinds = [e["event"] for e in events]
        assert "sweep_removed" in kinds
        assert "sweep_complete" in kinds
        complete = next(e for e in events if e["event"] == "sweep_complete")
        assert complete["removed"] == 1

    def test_empty_generated_dir_returns_zero(self, story_manager_with_generated):
        sm, generated = story_manager_with_generated
        assert sweep_generated(story_manager=sm, generated_dir=generated, now_seconds=time.time()) == 0

    def test_skips_non_uuid_dirs(self, story_manager_with_generated):
        sm, generated = story_manager_with_generated
        # Defense-in-depth: sweeper should not blow up on weird dirs
        (generated / ".trash").mkdir()
        assert sweep_generated(story_manager=sm, generated_dir=generated, now_seconds=time.time()) == 0
