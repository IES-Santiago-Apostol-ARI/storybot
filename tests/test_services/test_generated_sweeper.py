"""Wave 0 RED stubs for app.services.generated_sweeper (D-13).

These tests fail today because app.services.generated_sweeper does not exist.
Plan 16-01 makes them GREEN.
"""

import json
import time
from pathlib import Path

import pytest

# This import will FAIL today — RED.
pytest.importorskip(
    "app.services.generated_sweeper",
    reason="Wave 0 RED stub: implemented in Plan 16-01",
)

from app.services.generated_sweeper import (  # noqa: E402
    MAX_AGE_SECONDS,
    sweep_generated,
    sweep_orphan_story_dirs,
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
        removed = sweep_generated(
            story_manager=sm, generated_dir=generated, now_seconds=now
        )
        assert removed == 1
        assert not stale.exists()
        assert fresh.exists()

    def test_emits_stderr_json_per_removal(self, story_manager_with_generated, capsys):
        sm, generated = story_manager_with_generated
        now = time.time()
        _seed_dir(generated, "stale-uuid", age_seconds=8 * 86400, now=now)
        sweep_generated(story_manager=sm, generated_dir=generated, now_seconds=now)
        captured = capsys.readouterr()
        events = [
            json.loads(line)
            for line in captured.err.strip().split("\n")
            if line.strip()
        ]
        kinds = [e["event"] for e in events]
        assert "sweep_removed" in kinds
        assert "sweep_complete" in kinds
        complete = next(e for e in events if e["event"] == "sweep_complete")
        assert complete["removed"] == 1

    def test_empty_generated_dir_returns_zero(self, story_manager_with_generated):
        sm, generated = story_manager_with_generated
        assert (
            sweep_generated(
                story_manager=sm, generated_dir=generated, now_seconds=time.time()
            )
            == 0
        )

    def test_skips_non_uuid_dirs(self, story_manager_with_generated):
        sm, generated = story_manager_with_generated
        # Defense-in-depth: sweeper should not blow up on weird dirs
        (generated / ".trash").mkdir()
        assert (
            sweep_generated(
                story_manager=sm, generated_dir=generated, now_seconds=time.time()
            )
            == 0
        )


def _write_index(sm: StoryManager, story_ids: list[str]) -> None:
    """Point sm at a tmp index file holding exactly these story ids."""
    sm.INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    sm.INDEX_FILE.write_text(
        json.dumps(
            {
                "version": 2,
                "stories": {sid: {"id": sid} for sid in story_ids},
                "nfc_to_story": {},
                "cards": {},
            }
        )
    )


def _seed_cover_dir(
    parent: Path, story_id: str, age_seconds: float, now: float
) -> Path:
    """A generated dir holding only the GPIO button's cover PNGs (no story.json)."""
    import os

    d = parent / story_id
    d.mkdir()
    mtime = now - age_seconds
    for name in ("cover-preview.png", "cover-print.png"):
        f = d / name
        f.write_bytes(b"\x89PNG")
        os.utime(f, (mtime, mtime))
    os.utime(d, (mtime, mtime))
    return d


class TestSweepGeneratedCoverOnlyDirs:
    """The GPIO image button writes cover PNGs to content/generated/<id>/ for
    curated stories too, leaving dirs with no story.json behind."""

    @pytest.fixture
    def sm_with_trees(self, tmp_path):
        generated = tmp_path / "generated"
        generated.mkdir()
        sm = StoryManager()
        sm.GENERATED_DIR = generated
        sm.CONTENT_DIR = tmp_path / "stories"
        sm.INDEX_FILE = sm.CONTENT_DIR / "stories.json"
        return sm, generated

    def test_removes_stale_unreferenced_cover_dir(self, sm_with_trees):
        sm, generated = sm_with_trees
        now = time.time()
        _write_index(sm, ["live-story"])
        dead = _seed_cover_dir(generated, "dead-story", age_seconds=8 * 86400, now=now)
        removed = sweep_generated(
            story_manager=sm, generated_dir=generated, now_seconds=now
        )
        assert removed == 1
        assert not dead.exists()

    def test_keeps_cover_dir_of_live_curated_story(self, sm_with_trees):
        sm, generated = sm_with_trees
        now = time.time()
        _write_index(sm, ["live-story"])
        # Stale by age, but it IS the live story's current cover — deleting it
        # would 404 the kiosk image and break the print button.
        live = _seed_cover_dir(generated, "live-story", age_seconds=30 * 86400, now=now)
        assert (
            sweep_generated(story_manager=sm, generated_dir=generated, now_seconds=now)
            == 0
        )
        assert live.exists()

    def test_keeps_fresh_cover_dir(self, sm_with_trees):
        sm, generated = sm_with_trees
        now = time.time()
        _write_index(sm, ["live-story"])
        # A generation in flight has cover PNGs before story.json lands; the age
        # guard is what keeps the sweeper off it.
        inflight = _seed_cover_dir(generated, "in-flight", age_seconds=60, now=now)
        assert (
            sweep_generated(story_manager=sm, generated_dir=generated, now_seconds=now)
            == 0
        )
        assert inflight.exists()

    def test_keeps_dir_with_unrecognised_files(self, sm_with_trees):
        sm, generated = sm_with_trees
        now = time.time()
        _write_index(sm, ["live-story"])
        import os

        d = generated / "weird"
        d.mkdir()
        f = d / "notes.txt"
        f.write_text("x")
        os.utime(f, (now - 30 * 86400, now - 30 * 86400))
        assert (
            sweep_generated(story_manager=sm, generated_dir=generated, now_seconds=now)
            == 0
        )
        assert d.exists()

    def test_keeps_cover_dirs_when_index_missing(self, sm_with_trees):
        sm, generated = sm_with_trees
        now = time.time()
        # No index written: every cover dir would look unreferenced. Without
        # a readable index the sweeper cannot tell a live story's cover from a
        # dead one, so it must leave all of them alone.
        live = _seed_cover_dir(generated, "live-story", age_seconds=30 * 86400, now=now)
        assert (
            sweep_generated(story_manager=sm, generated_dir=generated, now_seconds=now)
            == 0
        )
        assert live.exists()

    def test_keeps_cover_dirs_when_index_has_no_stories(self, sm_with_trees):
        sm, generated = sm_with_trees
        now = time.time()
        _write_index(sm, [])
        live = _seed_cover_dir(generated, "live-story", age_seconds=30 * 86400, now=now)
        assert (
            sweep_generated(story_manager=sm, generated_dir=generated, now_seconds=now)
            == 0
        )
        assert live.exists()

    def test_stale_generated_dirs_still_swept_without_index(self, sm_with_trees):
        sm, generated = sm_with_trees
        now = time.time()
        # The story.json branch is self-describing and does not consult the
        # index, so a missing index must not disable it.
        stale = _seed_dir(generated, "stale-uuid", age_seconds=8 * 86400, now=now)
        assert (
            sweep_generated(story_manager=sm, generated_dir=generated, now_seconds=now)
            == 1
        )
        assert not stale.exists()

    def test_emits_json_event_for_cover_removal(self, sm_with_trees, capsys):
        sm, generated = sm_with_trees
        now = time.time()
        _write_index(sm, ["live-story"])
        _seed_cover_dir(generated, "dead-story", age_seconds=8 * 86400, now=now)
        sweep_generated(story_manager=sm, generated_dir=generated, now_seconds=now)
        events = [
            json.loads(line)
            for line in capsys.readouterr().err.strip().split("\n")
            if line.strip()
        ]
        removed = next(e for e in events if e["event"] == "sweep_removed")
        assert removed["id"] == "dead-story"
        assert removed["kind"] == "cover_only"


def _seed_story_dir(
    parent: Path, story_id: str, age_seconds: float, now: float
) -> Path:
    import os

    d = parent / story_id
    d.mkdir(parents=True)
    mtime = now - age_seconds
    f = d / "audio.mp3"
    f.write_bytes(b"ID3")
    os.utime(f, (mtime, mtime))
    os.utime(d, (mtime, mtime))
    return d


class TestSweepOrphanStoryDirs:
    """content/stories/<uuid>/ dirs that the index no longer references."""

    @pytest.fixture
    def sm_with_stories(self, tmp_path):
        stories = tmp_path / "stories"
        stories.mkdir()
        sm = StoryManager()
        sm.CONTENT_DIR = stories
        sm.INDEX_FILE = stories / "stories.json"
        return sm, stories

    def test_removes_stale_orphan(self, sm_with_stories):
        sm, stories = sm_with_stories
        now = time.time()
        _write_index(sm, ["keep-me", "keep-me-too"])
        _seed_story_dir(stories, "keep-me", age_seconds=99 * 86400, now=now)
        _seed_story_dir(stories, "keep-me-too", age_seconds=99 * 86400, now=now)
        orphan = _seed_story_dir(stories, "orphan", age_seconds=8 * 86400, now=now)
        removed = sweep_orphan_story_dirs(
            story_manager=sm, stories_dir=stories, now_seconds=now
        )
        assert removed == 1
        assert not orphan.exists()
        assert (stories / "keep-me").exists()

    def test_keeps_fresh_orphan(self, sm_with_stories):
        sm, stories = sm_with_stories
        now = time.time()
        _write_index(sm, ["keep-me"])
        _seed_story_dir(stories, "keep-me", age_seconds=99 * 86400, now=now)
        # An upload that is mid-flight has its dir before create_story lands.
        fresh = _seed_story_dir(stories, "fresh-orphan", age_seconds=60, now=now)
        assert (
            sweep_orphan_story_dirs(
                story_manager=sm, stories_dir=stories, now_seconds=now
            )
            == 0
        )
        assert fresh.exists()

    def test_skips_entirely_when_index_missing(self, sm_with_stories):
        sm, stories = sm_with_stories
        now = time.time()
        # No index file at all: every dir would look orphaned. Bail out rather
        # than delete the whole library.
        d = _seed_story_dir(
            stories, "would-look-orphaned", age_seconds=99 * 86400, now=now
        )
        assert (
            sweep_orphan_story_dirs(
                story_manager=sm, stories_dir=stories, now_seconds=now
            )
            == 0
        )
        assert d.exists()

    def test_skips_entirely_when_index_has_no_stories(self, sm_with_stories):
        sm, stories = sm_with_stories
        now = time.time()
        _write_index(sm, [])
        d = _seed_story_dir(
            stories, "would-look-orphaned", age_seconds=99 * 86400, now=now
        )
        assert (
            sweep_orphan_story_dirs(
                story_manager=sm, stories_dir=stories, now_seconds=now
            )
            == 0
        )
        assert d.exists()

    def test_circuit_breaker_when_orphans_outnumber_indexed(self, sm_with_stories):
        sm, stories = sm_with_stories
        now = time.time()
        _write_index(sm, ["only-one"])
        _seed_story_dir(stories, "only-one", age_seconds=99 * 86400, now=now)
        a = _seed_story_dir(stories, "orphan-a", age_seconds=99 * 86400, now=now)
        b = _seed_story_dir(stories, "orphan-b", age_seconds=99 * 86400, now=now)
        # Mass orphaning means a restored/corrupt index, not normal leakage.
        assert (
            sweep_orphan_story_dirs(
                story_manager=sm, stories_dir=stories, now_seconds=now
            )
            == 0
        )
        assert a.exists() and b.exists()

    def test_ignores_index_file_and_non_dirs(self, sm_with_stories):
        sm, stories = sm_with_stories
        now = time.time()
        _write_index(sm, ["keep-me"])
        _seed_story_dir(stories, "keep-me", age_seconds=99 * 86400, now=now)
        stray = stories / "README.txt"
        stray.write_text("x")
        assert (
            sweep_orphan_story_dirs(
                story_manager=sm, stories_dir=stories, now_seconds=now
            )
            == 0
        )
        assert sm.INDEX_FILE.exists()
        assert stray.exists()

    def test_emits_json_events(self, sm_with_stories, capsys):
        sm, stories = sm_with_stories
        now = time.time()
        _write_index(sm, ["keep-me", "keep-me-too"])
        _seed_story_dir(stories, "keep-me", age_seconds=99 * 86400, now=now)
        _seed_story_dir(stories, "keep-me-too", age_seconds=99 * 86400, now=now)
        _seed_story_dir(stories, "orphan", age_seconds=8 * 86400, now=now)
        sweep_orphan_story_dirs(story_manager=sm, stories_dir=stories, now_seconds=now)
        events = [
            json.loads(line)
            for line in capsys.readouterr().err.strip().split("\n")
            if line.strip()
        ]
        kinds = [e["event"] for e in events]
        assert "orphan_story_removed" in kinds
        assert "orphan_sweep_complete" in kinds
        assert (
            next(e for e in events if e["event"] == "orphan_story_removed")["id"]
            == "orphan"
        )
        assert (
            next(e for e in events if e["event"] == "orphan_sweep_complete")["removed"]
            == 1
        )

    def test_missing_stories_dir_returns_zero(self, sm_with_stories, tmp_path):
        sm, _ = sm_with_stories
        assert (
            sweep_orphan_story_dirs(
                story_manager=sm, stories_dir=tmp_path / "nope", now_seconds=time.time()
            )
            == 0
        )
