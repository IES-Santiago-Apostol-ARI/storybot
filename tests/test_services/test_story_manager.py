"""Tests for StoryManager service."""

import json
from pathlib import Path

import pytest

from app.models.story import Story
from app.services.story_manager import StoryManager


@pytest.fixture
def temp_content_dir(tmp_path: Path) -> Path:
    """Create a temporary content directory."""
    content_dir = tmp_path / "content" / "stories"
    content_dir.mkdir(parents=True)
    return content_dir


@pytest.fixture
def story_manager(temp_content_dir: Path) -> StoryManager:
    """Create a StoryManager with temporary directory."""
    # Patch the CONTENT_DIR to use temp directory
    manager = StoryManager()
    manager.CONTENT_DIR = temp_content_dir
    manager.INDEX_FILE = temp_content_dir / "stories.json"
    # Initialize empty index
    manager.INDEX_FILE.write_text(
        json.dumps({"version": 1, "stories": {}, "nfc_to_story": {}})
    )
    return manager


@pytest.fixture
def story_create_data() -> dict:
    """Sample story creation data."""
    return {
        "id": "test-story-1",
        "title": "Test Story",
        "emoji": "📚",
        "led_color": "#FF5733",
        "audio_file": "audio.mp3",
        "nfc_uid": None,
        "cover_image": None,
    }


class TestStoryManagerCreate:
    """Test StoryManager.create_story()."""

    def test_create_story_saves_to_index(
        self, story_manager: StoryManager, story_create_data: dict
    ):
        """Test that create_story saves story to index and returns Story object."""
        # Create story
        story = story_manager.create_story(**story_create_data)

        # Verify Story object returned
        assert isinstance(story, Story)
        assert story.id == "test-story-1"
        assert story.title == "Test Story"
        assert story.emoji == "📚"
        assert story.led_color == "#FF5733"
        assert story.audio_file == "audio.mp3"

        # Verify saved to index
        index = json.loads(story_manager.INDEX_FILE.read_text())
        assert "test-story-1" in index["stories"]
        assert index["stories"]["test-story-1"]["title"] == "Test Story"


class TestStoryManagerList:
    """Test StoryManager.list_stories()."""

    def test_list_stories_returns_all_stories(
        self, story_manager: StoryManager, story_create_data: dict
    ):
        """Test that list_stories returns all stories from index."""
        # Create multiple stories
        story_manager.create_story(**story_create_data)
        story_create_data["id"] = "test-story-2"
        story_create_data["title"] = "Another Story"
        story_manager.create_story(**story_create_data)

        # List stories
        stories = story_manager.list_stories()

        # Verify
        assert len(stories) == 2
        assert stories[0].id == "test-story-1"
        assert stories[1].id == "test-story-2"
        assert stories[0].title == "Test Story"
        assert stories[1].title == "Another Story"

    def test_list_stories_empty_returns_empty_list(self, story_manager: StoryManager):
        """Test that list_stories returns empty list when no stories."""
        stories = story_manager.list_stories()
        assert stories == []


class TestStoryManagerGet:
    """Test StoryManager.get_story()."""

    def test_get_story_returns_single_story(
        self, story_manager: StoryManager, story_create_data: dict
    ):
        """Test that get_story returns single story or None."""
        # Create story
        created = story_manager.create_story(**story_create_data)

        # Get story
        story = story_manager.get_story("test-story-1")

        # Verify
        assert story is not None
        assert story.id == "test-story-1"
        assert story.title == "Test Story"
        assert story.emoji == "📚"

    def test_get_story_not_found_returns_none(self, story_manager: StoryManager):
        """Test that get_story returns None for non-existent story."""
        story = story_manager.get_story("non-existent")
        assert story is None


class TestStoryManagerDelete:
    """Test StoryManager.delete_story()."""

    def test_delete_story_removes_from_index(
        self, story_manager: StoryManager, story_create_data: dict
    ):
        """Test that delete_story removes story from index."""
        # Create story
        story_manager.create_story(**story_create_data)

        # Verify it exists
        assert story_manager.get_story("test-story-1") is not None

        # Delete story
        result = story_manager.delete_story("test-story-1")

        # Verify deletion
        assert result is True
        assert story_manager.get_story("test-story-1") is None

        # Verify removed from index
        index = json.loads(story_manager.INDEX_FILE.read_text())
        assert "test-story-1" not in index["stories"]

    def test_delete_story_not_found_returns_false(self, story_manager: StoryManager):
        """Test that delete_story returns False for non-existent story."""
        result = story_manager.delete_story("non-existent")
        assert result is False


class TestStoryManagerNFC:
    """Test StoryManager NFC assignment and lookup."""

    def test_assign_nfc_updates_story(
        self, story_manager: StoryManager, story_create_data: dict
    ):
        """Test that assign_nfc updates story's nfc_uid field."""
        # Create story
        story_manager.create_story(**story_create_data)

        # Assign NFC
        result = story_manager.assign_nfc("test-story-1", "04:A3:B5:C7:D9")

        # Verify returns Story object
        assert isinstance(result, Story)
        assert result.id == "test-story-1"
        assert result.nfc_uid == "04:A3:B5:C7:D9"

        # Verify story was updated
        story = story_manager.get_story("test-story-1")
        assert story.nfc_uid == "04:A3:B5:C7:D9"

        # Verify NFC mapping in index
        index = json.loads(story_manager.INDEX_FILE.read_text())
        assert index["nfc_to_story"]["04:A3:B5:C7:D9"] == "test-story-1"

    def test_assign_nfc_non_existent_story_returns_false(
        self, story_manager: StoryManager
    ):
        """Test that assign_nfc returns None for non-existent story."""
        result = story_manager.assign_nfc("non-existent", "04:A3:B5:C7:D9")
        assert result is None

    def test_get_story_by_nfc_returns_story(
        self, story_manager: StoryManager, story_create_data: dict
    ):
        """Test that get_story_by_nfc returns story for given NFC UID."""
        # Create story and assign NFC
        story_manager.create_story(**story_create_data)
        story_manager.assign_nfc("test-story-1", "04:A3:B5:C7:D9")

        # Get by NFC
        story = story_manager.get_story_by_nfc("04:A3:B5:C7:D9")

        # Verify
        assert story is not None
        assert story.id == "test-story-1"
        assert story.title == "Test Story"

    def test_get_story_by_nfc_not_found_returns_none(self, story_manager: StoryManager):
        """Test that get_story_by_nfc returns None for unknown NFC UID."""
        story = story_manager.get_story_by_nfc("unknown-uid")
        assert story is None

    def test_assign_nfc_replaces_existing_nfc(
        self, story_manager: StoryManager, story_create_data: dict
    ):
        """Test that assigning new NFC replaces old one."""
        # Create story and assign first NFC
        story_manager.create_story(**story_create_data)
        story_manager.assign_nfc("test-story-1", "old-nfc-uid")

        # Assign new NFC
        story_manager.assign_nfc("test-story-1", "new-nfc-uid")

        # Verify only new NFC is mapped
        story = story_manager.get_story("test-story-1")
        assert story.nfc_uid == "new-nfc-uid"

        index = json.loads(story_manager.INDEX_FILE.read_text())
        assert "old-nfc-uid" not in index["nfc_to_story"]
        assert index["nfc_to_story"]["new-nfc-uid"] == "test-story-1"


class TestStoryManagerUpdate:
    """Test StoryManager.update_story()."""

    def test_update_story_title(
        self, story_manager: StoryManager, story_create_data: dict
    ):
        """Test that update_story updates title."""
        # Create story
        story_manager.create_story(**story_create_data)

        # Update title
        result = story_manager.update_story("test-story-1", title="Updated Title")

        # Verify returns Story with new title
        assert result is not None
        assert result.id == "test-story-1"
        assert result.title == "Updated Title"

        # Verify story was updated
        story = story_manager.get_story("test-story-1")
        assert story.title == "Updated Title"

    def test_update_story_emoji_and_led_color(
        self, story_manager: StoryManager, story_create_data: dict
    ):
        """Test that update_story updates emoji and led_color."""
        # Create story
        story_manager.create_story(**story_create_data)

        # Update emoji and led_color
        result = story_manager.update_story(
            "test-story-1", emoji="🎉", led_color="#00FF00"
        )

        # Verify returns Story with new values
        assert result is not None
        assert result.emoji == "🎉"
        assert result.led_color == "#00FF00"

    def test_update_story_invalid_id_returns_none(
        self, story_manager: StoryManager, story_create_data: dict
    ):
        """Test that update_story returns None for invalid story_id."""
        # Create story
        story_manager.create_story(**story_create_data)

        # Try to update non-existent story
        result = story_manager.update_story("non-existent", title="New Title")
        assert result is None

    def test_update_story_with_new_audio_file(
        self, story_manager: StoryManager, story_create_data: dict
    ):
        """Test that update_story can update audio_file."""
        # Create story
        story_manager.create_story(**story_create_data)

        # Update audio file
        result = story_manager.update_story("test-story-1", audio_file="new_audio.wav")

        # Verify audio_file updated
        assert result is not None
        assert result.audio_file == "new_audio.wav"

        story = story_manager.get_story("test-story-1")
        assert story.audio_file == "new_audio.wav"

    def test_update_story_with_new_cover_image(
        self, story_manager: StoryManager, story_create_data: dict
    ):
        """Test that update_story can update cover_image."""
        # Create story
        story_manager.create_story(**story_create_data)

        # Update cover image
        result = story_manager.update_story("test-story-1", cover_image="new_cover.jpg")

        # Verify cover_image updated
        assert result is not None
        assert result.cover_image == "new_cover.jpg"

    def test_update_story_remove_cover_clears_cover_image(
        self, story_manager: StoryManager, story_create_data: dict
    ):
        """Test that update_story with remove_cover=True clears cover_image."""
        # Create story with cover
        story_create_data["cover_image"] = "cover.jpg"
        story_manager.create_story(**story_create_data)

        # Verify cover exists
        story = story_manager.get_story("test-story-1")
        assert story.cover_image == "cover.jpg"

        # Remove cover
        result = story_manager.update_story("test-story-1", remove_cover=True)

        # Verify cover_image is None
        assert result is not None
        assert result.cover_image is None

        story = story_manager.get_story("test-story-1")
        assert story.cover_image is None

    def test_update_story_preserves_nfc_uid(
        self, story_manager: StoryManager, story_create_data: dict
    ):
        """Test that update_story preserves nfc_uid."""
        # Create story with NFC
        story_manager.create_story(**story_create_data)
        story_manager.assign_nfc("test-story-1", "04:A3:B5:C7:D9")

        # Update title
        result = story_manager.update_story("test-story-1", title="Updated Title")

        # Verify NFC UID is preserved
        assert result is not None
        assert result.nfc_uid == "04:A3:B5:C7:D9"

        story = story_manager.get_story("test-story-1")
        assert story.nfc_uid == "04:A3:B5:C7:D9"

    def test_update_story_preserves_created_at(
        self, story_manager: StoryManager, story_create_data: dict
    ):
        """Test that update_story preserves created_at timestamp."""
        # Create story
        created = story_manager.create_story(**story_create_data)
        original_timestamp = created.created_at

        # Update title
        result = story_manager.update_story("test-story-1", title="Updated Title")

        # Verify created_at is preserved
        assert result is not None
        assert result.created_at == original_timestamp


class TestStoryTranscript:
    """PLAN.md Task 4: transcript stored as story text metadata."""

    def test_created_story_has_no_transcript(
        self, story_manager: StoryManager, story_create_data: dict
    ):
        story = story_manager.create_story(**story_create_data)

        assert story.transcript is None

    def test_update_story_transcript_persists_to_index(
        self, story_manager: StoryManager, story_create_data: dict
    ):
        story_manager.create_story(**story_create_data)

        result = story_manager.update_story(
            "test-story-1", transcript="Había una vez un robot."
        )

        assert result is not None
        assert result.transcript == "Había una vez un robot."
        index = json.loads(story_manager.INDEX_FILE.read_text())
        assert (
            index["stories"]["test-story-1"]["transcript"] == "Había una vez un robot."
        )

    def test_update_story_transcript_leaves_other_fields_untouched(
        self, story_manager: StoryManager, story_create_data: dict
    ):
        created = story_manager.create_story(**story_create_data)

        result = story_manager.update_story("test-story-1", transcript="Texto.")

        assert result.title == created.title
        assert result.audio_file == created.audio_file
        assert result.created_at == created.created_at

    def test_update_without_transcript_preserves_existing_transcript(
        self, story_manager: StoryManager, story_create_data: dict
    ):
        story_manager.create_story(**story_create_data)
        story_manager.update_story("test-story-1", transcript="Texto.")

        result = story_manager.update_story("test-story-1", title="New Title")

        assert result.transcript == "Texto."

    def test_pre_transcript_index_entries_load_fine(
        self, story_manager: StoryManager, story_create_data: dict
    ):
        """Old stories.json entries have no transcript key at all."""
        story_manager.create_story(**story_create_data)
        index = json.loads(story_manager.INDEX_FILE.read_text())
        index["stories"]["test-story-1"].pop("transcript", None)
        story_manager.INDEX_FILE.write_text(json.dumps(index))

        story = story_manager.get_story("test-story-1")

        assert story is not None
        assert story.transcript is None


class TestPruneGenerated:
    """PLAN.md Task 3: prune_generated caps the number of generated stories."""

    def _make_generated_dir(
        self, tmp_path: Path, names_with_dates: list[tuple[str, str]]
    ):
        """Create content/generated/<name>/story.json for each (id, ISO created_at)."""
        gen_dir = tmp_path / "content" / "generated"
        gen_dir.mkdir(parents=True)
        for name, created_at in names_with_dates:
            story_dir = gen_dir / name
            story_dir.mkdir(parents=True, exist_ok=True)
            (story_dir / "story.json").write_text(
                json.dumps({"id": name, "created_at": created_at, "text": ""})
            )
        return gen_dir

    def test_prune_generated_removes_oldest_until_count_le_max(self, tmp_path):
        """5 stories exist, prune to 3: 2 oldest (by created_at) are deleted."""
        gen_dir = self._make_generated_dir(
            tmp_path,
            [
                ("aaa-oldest", "2026-01-01T00:00:00+00:00"),
                ("bbb-old", "2026-02-01T00:00:00+00:00"),
                ("ccc-mid", "2026-03-01T00:00:00+00:00"),
                ("ddd-new", "2026-04-01T00:00:00+00:00"),
                ("eee-newest", "2026-05-01T00:00:00+00:00"),
            ],
        )

        manager = StoryManager()
        manager.CONTENT_DIR = tmp_path / "content" / "stories"
        manager.INDEX_FILE = tmp_path / "content" / "stories" / "stories.json"
        manager.INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
        manager.INDEX_FILE.write_text(
            json.dumps({"version": 1, "stories": {}, "nfc_to_story": {}})
        )
        manager.GENERATED_DIR = gen_dir

        manager.prune_generated(3)

        remaining = list(gen_dir.iterdir())
        assert len(remaining) == 3
        remaining_ids = {d.name for d in remaining}
        assert remaining_ids == {"ccc-mid", "ddd-new", "eee-newest"}

    def test_prune_generated_noop_when_count_below_max(self, tmp_path):
        """2 stories exist, prune to 5: nothing is deleted."""
        gen_dir = self._make_generated_dir(
            tmp_path,
            [
                ("aaa", "2026-01-01T00:00:00+00:00"),
                ("bbb", "2026-02-01T00:00:00+00:00"),
            ],
        )

        manager = StoryManager()
        manager.CONTENT_DIR = tmp_path / "content" / "stories"
        manager.INDEX_FILE = tmp_path / "content" / "stories" / "stories.json"
        manager.INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
        manager.INDEX_FILE.write_text(
            json.dumps({"version": 1, "stories": {}, "nfc_to_story": {}})
        )
        manager.GENERATED_DIR = gen_dir

        manager.prune_generated(5)

        remaining = list(gen_dir.iterdir())
        assert len(remaining) == 2

    def test_prune_generated_noop_when_empty(self, tmp_path):
        """No generated stories exist: prune is a no-op."""
        gen_dir = tmp_path / "content" / "generated"
        gen_dir.mkdir(parents=True)

        manager = StoryManager()
        manager.CONTENT_DIR = tmp_path / "content" / "stories"
        manager.INDEX_FILE = tmp_path / "content" / "stories" / "stories.json"
        manager.INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
        manager.INDEX_FILE.write_text(
            json.dumps({"version": 1, "stories": {}, "nfc_to_story": {}})
        )
        manager.GENERATED_DIR = gen_dir

        manager.prune_generated(5)

        remaining = list(gen_dir.iterdir())
        assert remaining == []

    def test_prune_generated_with_only_invalid_story_dirs_skipped(self, tmp_path):
        """Dirs without story.json are left alone by prune."""
        gen_dir = tmp_path / "content" / "generated"
        gen_dir.mkdir(parents=True)
        # A dir without story.json
        (gen_dir / "no-json").mkdir(parents=True, exist_ok=True)
        (gen_dir / "no-json" / "random.txt").write_text("junk")

        manager = StoryManager()
        manager.CONTENT_DIR = tmp_path / "content" / "stories"
        manager.INDEX_FILE = tmp_path / "content" / "stories" / "stories.json"
        manager.INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
        manager.INDEX_FILE.write_text(
            json.dumps({"version": 1, "stories": {}, "nfc_to_story": {}})
        )
        manager.GENERATED_DIR = gen_dir

        manager.prune_generated(5)

        assert (gen_dir / "no-json").exists()


class TestCreatedAtTimestamp:
    """IMPROVEMENTS.md 2.5: standardize on datetime.now(timezone.utc)."""

    def test_created_at_is_timezone_aware_utc(
        self, story_manager: StoryManager, story_create_data: dict
    ):
        """created_at must parse with datetime.fromisoformat (no 'Z' suffix
        from the deprecated utcnow() idiom) and carry a UTC offset."""
        from datetime import datetime, timedelta

        story = story_manager.create_story(**story_create_data)
        parsed = datetime.fromisoformat(story.created_at)
        assert parsed.tzinfo is not None
        assert parsed.utcoffset() == timedelta(0)


class TestAtomicWrites:
    """IMPROVE.md Task 2: _save_index routes through write_json_atomic."""

    def test_create_story_uses_atomic_write(
        self, story_manager: StoryManager, story_create_data: dict, monkeypatch
    ):
        """create_story never observes a truncated index: _save_index calls
        write_json_atomic, not raw open/write."""
        # Use v2 index so _migrate_v1_to_v2 doesn't add an extra _save_index call
        story_manager.INDEX_FILE.write_text(
            json.dumps({"version": 2, "stories": {}, "nfc_to_story": {}, "cards": {}})
        )

        call_count = {"n": 0}

        def counting_write(path, data, **kwargs):
            call_count["n"] += 1

        monkeypatch.setattr(
            "app.services.story_manager.write_json_atomic", counting_write
        )

        story_manager.create_story(**story_create_data)

        assert call_count["n"] == 1

    def test_attach_cover_uses_atomic_write(
        self, story_manager: StoryManager, tmp_path: Path, monkeypatch
    ):
        """attach_cover uses write_json_atomic instead of manual tmp+rename."""
        gen_dir = tmp_path / "content" / "generated" / "test-id"
        gen_dir.mkdir(parents=True)
        story_file = gen_dir / "story.json"
        story_file.write_text(json.dumps({"id": "test-id", "text": ""}))

        story_manager.GENERATED_DIR = tmp_path / "content" / "generated"

        call_count = {"n": 0}

        def counting_write(path, data, **kwargs):
            call_count["n"] += 1

        monkeypatch.setattr(
            "app.services.story_manager.write_json_atomic", counting_write
        )

        story_manager.attach_cover("test-id", "/fake/preview.png", "/fake/print.png")

        assert call_count["n"] == 1
