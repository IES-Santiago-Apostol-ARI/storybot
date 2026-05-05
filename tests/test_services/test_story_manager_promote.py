"""Wave 0 RED stubs for StoryManager promote/list/delete generated (D-11).

Plan 16-02 turns these GREEN.
"""

import json
import wave
from pathlib import Path

import pytest

from app.services.story_manager import StoryManager


@pytest.fixture
def story_manager(tmp_path):
    content = tmp_path / "content" / "stories"
    content.mkdir(parents=True)
    generated = tmp_path / "content" / "generated"
    generated.mkdir(parents=True)
    sm = StoryManager()
    sm.CONTENT_DIR = content
    sm.GENERATED_DIR = generated
    sm.INDEX_FILE = content / "stories.json"
    sm.INDEX_FILE.write_text(json.dumps({"version": 1, "stories": {}, "nfc_to_story": {}}))
    return sm


def _write_silent_wav(path: Path, frames: int = 22050) -> None:
    """Write a minimal mono 22050 Hz 16-bit WAV with `frames` samples of silence."""
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(b"\x00\x00" * frames)


def _seed_generated(sm: StoryManager, story_id: str, n_segments: int = 2) -> Path:
    d = sm.GENERATED_DIR / story_id
    audio = d / "audio"
    audio.mkdir(parents=True)
    for i in range(n_segments):
        _write_silent_wav(audio / f"{i:03d}.wav", frames=22050)
    (d / "story.json").write_text(
        json.dumps({
            "id": story_id,
            "text": "Había una vez",
            "parameters": [{"category": "personaje", "value": "dragón"}],
            "created_at": "2026-04-27T00:00:00Z",
            "cover": {"preview": "cover-preview.png", "print": "cover-print.png"},
        })
    )
    (d / "cover-preview.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (d / "cover-print.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return d


class TestStoryManagerListGenerated:
    def test_list_returns_summaries(self, story_manager):
        if not hasattr(story_manager, "list_generated"):
            pytest.fail("RED: StoryManager.list_generated not implemented (Plan 16-02)")
        _seed_generated(story_manager, "uuid-a")
        _seed_generated(story_manager, "uuid-b")
        rows = story_manager.list_generated()
        assert len(rows) == 2
        ids = {r["id"] for r in rows}
        assert ids == {"uuid-a", "uuid-b"}
        for r in rows:
            assert "text_preview" in r
            assert "parameters" in r
            assert "created_at" in r

    def test_list_empty(self, story_manager):
        if not hasattr(story_manager, "list_generated"):
            pytest.fail("RED: StoryManager.list_generated not implemented (Plan 16-02)")
        assert story_manager.list_generated() == []


class TestStoryManagerDeleteGenerated:
    def test_delete_removes_dir(self, story_manager):
        if not hasattr(story_manager, "delete_generated"):
            pytest.fail("RED: StoryManager.delete_generated not implemented (Plan 16-02)")
        d = _seed_generated(story_manager, "uuid-a")
        assert story_manager.delete_generated("uuid-a") is True
        assert not d.exists()

    def test_delete_missing_returns_false(self, story_manager):
        if not hasattr(story_manager, "delete_generated"):
            pytest.fail("RED: StoryManager.delete_generated not implemented (Plan 16-02)")
        assert story_manager.delete_generated("uuid-missing") is False


class TestStoryManagerPromoteGenerated:
    def test_promote_creates_curated_story_with_concatenated_audio(self, story_manager):
        if not hasattr(story_manager, "promote_generated"):
            pytest.fail("RED: StoryManager.promote_generated not implemented (Plan 16-02)")
        _seed_generated(story_manager, "uuid-a", n_segments=3)
        new_story = story_manager.promote_generated(
            generated_id="uuid-a",
            title="Mi cuento",
            emoji="🐉",
            led_color="#FF5733",
        )
        # New curated story exists in index
        assert new_story.title == "Mi cuento"
        assert new_story.emoji == "🐉"
        # Generated dir is gone (delete-on-promote per RESEARCH §3)
        assert not (story_manager.GENERATED_DIR / "uuid-a").exists()
        # Audio file is a single concatenated WAV
        curated_dir = story_manager.CONTENT_DIR / new_story.id
        audio_file = curated_dir / new_story.audio_file
        assert audio_file.exists()
        with wave.open(str(audio_file), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getframerate() == 22050
            # 3 segments × 22050 frames each
            assert wf.getnframes() == 3 * 22050

    def test_promote_copies_cover(self, story_manager):
        if not hasattr(story_manager, "promote_generated"):
            pytest.fail("RED: StoryManager.promote_generated not implemented (Plan 16-02)")
        _seed_generated(story_manager, "uuid-a")
        new_story = story_manager.promote_generated(
            generated_id="uuid-a", title="T", emoji="🐉", led_color="#FF5733"
        )
        curated_dir = story_manager.CONTENT_DIR / new_story.id
        # cover-preview.png copied into curated dir
        assert (curated_dir / "cover-preview.png").exists() or new_story.cover_image is not None

    def test_promote_missing_id_raises(self, story_manager):
        if not hasattr(story_manager, "promote_generated"):
            pytest.fail("RED: StoryManager.promote_generated not implemented (Plan 16-02)")
        with pytest.raises((FileNotFoundError, ValueError)):
            story_manager.promote_generated(
                generated_id="nope", title="T", emoji="🐉", led_color="#FF5733"
            )
