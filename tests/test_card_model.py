"""Tests for card type data model and stories.json migration."""

import json
from pathlib import Path

import pytest

from app.models.card import CardType, GoCard, ParameterCard
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
    manager = StoryManager()
    manager.CONTENT_DIR = temp_content_dir
    manager.INDEX_FILE = temp_content_dir / "stories.json"
    manager.INDEX_FILE.write_text(
        json.dumps({"version": 1, "stories": {}, "nfc_to_story": {}})
    )
    return manager


@pytest.fixture
def v1_index_with_nfc(temp_content_dir: Path) -> StoryManager:
    """Create a StoryManager with v1 data that needs migration."""
    manager = StoryManager()
    manager.CONTENT_DIR = temp_content_dir
    manager.INDEX_FILE = temp_content_dir / "stories.json"
    manager.INDEX_FILE.write_text(
        json.dumps(
            {
                "version": 1,
                "stories": {
                    "story-1": {
                        "id": "story-1",
                        "title": "Dragon Story",
                        "emoji": "🐉",
                        "led_color": "#FF5733",
                        "audio_file": "audio.mp3",
                        "nfc_uid": "AA:BB:CC:DD",
                        "cover_image": None,
                        "created_at": "2026-01-01T00:00:00Z",
                    }
                },
                "nfc_to_story": {"AA:BB:CC:DD": "story-1"},
            }
        )
    )
    return manager


class TestCardTypeEnum:
    """Test CardType enum values."""

    def test_card_type_values(self):
        assert CardType.STORY == "story"
        assert CardType.PARAMETER == "parameter"
        assert CardType.GO == "go"

    def test_card_type_from_string(self):
        assert CardType("story") == CardType.STORY
        assert CardType("parameter") == CardType.PARAMETER
        assert CardType("go") == CardType.GO


class TestParameterCard:
    """Test ParameterCard model validation."""

    def test_valid_parameter_card(self):
        card = ParameterCard(
            uid="11:22:33:44",
            category="character",
            value="dragon",
            emoji="🐉",
            label="Dragón",
        )
        assert card.type == CardType.PARAMETER
        assert card.category == "character"
        assert card.value == "dragon"

    def test_parameter_card_requires_all_fields(self):
        with pytest.raises(Exception):
            ParameterCard(uid="11:22:33:44")

    def test_parameter_card_requires_category(self):
        with pytest.raises(Exception):
            ParameterCard(uid="11:22:33:44", value="dragon", emoji="🐉", label="D")


class TestGoCard:
    """Test GoCard model validation."""

    def test_valid_go_card(self):
        card = GoCard(uid="99:88:77:66")
        assert card.type == CardType.GO
        assert card.uid == "99:88:77:66"


class TestMigrationV1ToV2:
    """Test stories.json v1 → v2 migration."""

    def test_migration_populates_cards_dict(self, v1_index_with_nfc: StoryManager):
        """V1 index with nfc_to_story gets cards dict on load."""
        index = v1_index_with_nfc._load_index()

        assert index["version"] == 2
        assert "cards" in index
        assert "AA:BB:CC:DD" in index["cards"]
        card = index["cards"]["AA:BB:CC:DD"]
        assert card["type"] == "story"
        assert card["story_id"] == "story-1"

    def test_migration_preserves_nfc_to_story(self, v1_index_with_nfc: StoryManager):
        """nfc_to_story dict is preserved after migration."""
        index = v1_index_with_nfc._load_index()

        assert "nfc_to_story" in index
        assert index["nfc_to_story"]["AA:BB:CC:DD"] == "story-1"

    def test_migration_preserves_stories(self, v1_index_with_nfc: StoryManager):
        """Stories dict is preserved after migration."""
        index = v1_index_with_nfc._load_index()

        assert "story-1" in index["stories"]
        assert index["stories"]["story-1"]["title"] == "Dragon Story"

    def test_get_story_by_nfc_works_after_migration(
        self, v1_index_with_nfc: StoryManager
    ):
        """Existing get_story_by_nfc() works after migration."""
        story = v1_index_with_nfc.get_story_by_nfc("AA:BB:CC:DD")
        assert story is not None
        assert story.id == "story-1"
        assert story.title == "Dragon Story"

    def test_migration_empty_index(self, story_manager: StoryManager):
        """Empty v1 index migrates cleanly."""
        index = story_manager._load_index()
        assert index["version"] == 2
        assert "cards" in index
        assert index["cards"] == {}


class TestGetCard:
    """Test StoryManager.get_card()."""

    def test_get_card_returns_card_data(self, v1_index_with_nfc: StoryManager):
        """get_card() returns card dict for registered uid."""
        card = v1_index_with_nfc.get_card("AA:BB:CC:DD")
        assert card is not None
        assert card["type"] == "story"
        assert card["story_id"] == "story-1"

    def test_get_card_returns_none_for_unknown(self, story_manager: StoryManager):
        """get_card() returns None for unregistered uid."""
        card = story_manager.get_card("UNKNOWN")
        assert card is None


class TestCreateCard:
    """Test StoryManager.create_card()."""

    def test_create_parameter_card(self, story_manager: StoryManager):
        """create_card() stores a parameter card in the index."""
        card_data = {
            "uid": "11:22:33:44",
            "type": "parameter",
            "category": "character",
            "value": "dragon",
            "emoji": "🐉",
            "label": "Dragón",
        }
        result = story_manager.create_card(card_data)

        assert result["uid"] == "11:22:33:44"
        assert result["type"] == "parameter"
        assert result["category"] == "character"

    def test_create_go_card(self, story_manager: StoryManager):
        """create_card() stores a go card in the index."""
        card_data = {"uid": "99:88:77:66", "type": "go"}
        result = story_manager.create_card(card_data)

        assert result["uid"] == "99:88:77:66"
        assert result["type"] == "go"

    def test_create_card_rejects_duplicate_uid_in_nfc_to_story(
        self, v1_index_with_nfc: StoryManager
    ):
        """create_card() raises ValueError if uid already in nfc_to_story."""
        card_data = {
            "uid": "AA:BB:CC:DD",
            "type": "parameter",
            "category": "character",
            "value": "dragon",
            "emoji": "🐉",
            "label": "Dragón",
        }
        with pytest.raises(ValueError, match="already registered"):
            v1_index_with_nfc.create_card(card_data)

    def test_create_card_rejects_duplicate_uid_in_cards(
        self, story_manager: StoryManager
    ):
        """create_card() raises ValueError if uid already in cards."""
        card_data = {
            "uid": "11:22:33:44",
            "type": "parameter",
            "category": "character",
            "value": "dragon",
            "emoji": "🐉",
            "label": "Dragón",
        }
        story_manager.create_card(card_data)

        with pytest.raises(ValueError, match="already registered"):
            story_manager.create_card(card_data)


class TestDeleteCard:
    """Test StoryManager.delete_card()."""

    def test_delete_card_removes_from_index(self, story_manager: StoryManager):
        """delete_card() removes a parameter card."""
        card_data = {
            "uid": "11:22:33:44",
            "type": "parameter",
            "category": "character",
            "value": "dragon",
            "emoji": "🐉",
            "label": "Dragón",
        }
        story_manager.create_card(card_data)
        result = story_manager.delete_card("11:22:33:44")

        assert result is True
        assert story_manager.get_card("11:22:33:44") is None

    def test_delete_card_not_found(self, story_manager: StoryManager):
        """delete_card() returns False for unknown uid."""
        result = story_manager.delete_card("UNKNOWN")
        assert result is False

    def test_delete_story_type_card_raises(self, v1_index_with_nfc: StoryManager):
        """delete_card() raises ValueError for story-type cards."""
        with pytest.raises(ValueError, match="story-type card"):
            v1_index_with_nfc.delete_card("AA:BB:CC:DD")


class TestAssignNfcAlsoUpdatesCards:
    """Test that assign_nfc() also creates card entry."""

    def test_assign_nfc_creates_card_entry(self, story_manager: StoryManager):
        """assign_nfc() also adds entry to cards dict."""
        story_manager.create_story(
            id="s1",
            title="Test",
            emoji="📖",
            led_color="#FF0000",
            audio_file="audio.mp3",
        )
        story_manager.assign_nfc("s1", "AA:BB:CC:DD")

        card = story_manager.get_card("AA:BB:CC:DD")
        assert card is not None
        assert card["type"] == "story"
        assert card["story_id"] == "s1"

    def test_assign_nfc_reassignment_updates_cards(
        self, story_manager: StoryManager
    ):
        """Reassigning NFC removes old card entry, creates new one."""
        story_manager.create_story(
            id="s1",
            title="Story 1",
            emoji="📖",
            led_color="#FF0000",
            audio_file="audio.mp3",
        )
        story_manager.create_story(
            id="s2",
            title="Story 2",
            emoji="📚",
            led_color="#00FF00",
            audio_file="audio2.mp3",
        )
        story_manager.assign_nfc("s1", "AA:BB:CC:DD")
        story_manager.assign_nfc("s2", "AA:BB:CC:DD")

        card = story_manager.get_card("AA:BB:CC:DD")
        assert card["story_id"] == "s2"


class TestStoryDeleteRemovesCard:
    """Test that delete_story() also removes card entry."""

    def test_delete_story_removes_card_entry(self, story_manager: StoryManager):
        """delete_story() also removes the card from cards dict."""
        story_manager.create_story(
            id="s1",
            title="Test",
            emoji="📖",
            led_color="#FF0000",
            audio_file="audio.mp3",
            nfc_uid="AA:BB:CC:DD",
        )
        assert story_manager.get_card("AA:BB:CC:DD") is not None

        story_manager.delete_story("s1")
        assert story_manager.get_card("AA:BB:CC:DD") is None
