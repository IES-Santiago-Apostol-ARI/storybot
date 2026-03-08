"""Story manager service for CRUD operations and NFC mapping."""

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path

from app.models.story import Story, StoryCreate


class StoryManager:
    """Manager for story CRUD operations with JSON index persistence."""

    CONTENT_DIR = Path("content/stories")
    INDEX_FILE = CONTENT_DIR / "stories.json"

    def __init__(self) -> None:
        """Initialize StoryManager."""
        self._lock = threading.Lock()

    def _load_index(self) -> dict:
        """Load story index from JSON file.

        Returns:
            dict with keys: version, stories, nfc_to_story
        """
        if not self.INDEX_FILE.exists():
            return {"version": 1, "stories": {}, "nfc_to_story": {}}

        with open(self.INDEX_FILE, "r") as f:
            return json.load(f)

    def _save_index(self, index: dict) -> None:
        """Save story index to JSON file.

        Args:
            index: dict with keys: version, stories, nfc_to_story
        """
        self.INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(self.INDEX_FILE, "w") as f:
            json.dump(index, f, indent=2)

    def create_story(
        self,
        id: str,
        title: str,
        emoji: str,
        led_color: str,
        audio_file: str,
        nfc_uid: str | None = None,
        cover_image: str | None = None,
    ) -> Story:
        """Create a new story.

        Args:
            id: Story ID (UUID)
            title: Story title
            emoji: Story emoji icon
            led_color: LED color in hex format
            audio_file: Audio file name
            nfc_uid: Optional NFC card UID
            cover_image: Optional cover image file name

        Returns:
            Created Story object
        """
        with self._lock:
            index = self._load_index()

            story_data = {
                "id": id,
                "title": title,
                "emoji": emoji,
                "led_color": led_color,
                "audio_file": audio_file,
                "cover_image": cover_image,
                "nfc_uid": nfc_uid,
                "created_at": datetime.utcnow().isoformat() + "Z",
            }

            index["stories"][id] = story_data

            # Also map NFC UID if provided
            if nfc_uid:
                index["nfc_to_story"][nfc_uid] = id

            self._save_index(index)

            return Story(**story_data)

    def list_stories(self) -> list[Story]:
        """List all stories.

        Returns:
            List of Story objects
        """
        with self._lock:
            index = self._load_index()
            return [Story(**story_data) for story_data in index["stories"].values()]

    def get_story(self, story_id: str) -> Story | None:
        """Get a single story by ID.

        Args:
            story_id: Story ID

        Returns:
            Story object or None if not found
        """
        with self._lock:
            index = self._load_index()
            story_data = index["stories"].get(story_id)
            if story_data:
                return Story(**story_data)
            return None

    def delete_story(self, story_id: str) -> bool:
        """Delete a story by ID.

        Args:
            story_id: Story ID

        Returns:
            True if deleted, False if not found
        """
        with self._lock:
            index = self._load_index()

            if story_id not in index["stories"]:
                return False

            # Remove NFC mapping if exists
            story_data = index["stories"][story_id]
            if story_data.get("nfc_uid"):
                nfc_uid = story_data["nfc_uid"]
                if nfc_uid in index["nfc_to_story"]:
                    del index["nfc_to_story"][nfc_uid]

            # Remove story
            del index["stories"][story_id]
            self._save_index(index)

            return True

    def assign_nfc(self, story_id: str, nfc_uid: str) -> Story | None:
        """Assign an NFC card UID to a story.

        Args:
            story_id: Story ID
            nfc_uid: NFC card UID

        Returns:
            Updated Story if assigned, None if story not found
        """
        with self._lock:
            index = self._load_index()

            if story_id not in index["stories"]:
                return None

            # Remove old NFC mapping if exists
            old_nfc_uid = index["stories"][story_id].get("nfc_uid")
            if old_nfc_uid and old_nfc_uid in index["nfc_to_story"]:
                del index["nfc_to_story"][old_nfc_uid]

            # Update story with new NFC UID
            index["stories"][story_id]["nfc_uid"] = nfc_uid
            index["nfc_to_story"][nfc_uid] = story_id

            self._save_index(index)
            return Story(**index["stories"][story_id])

    def get_story_by_nfc(self, nfc_uid: str) -> Story | None:
        """Get a story by NFC card UID.

        Args:
            nfc_uid: NFC card UID

        Returns:
            Story object or None if not found
        """
        with self._lock:
            index = self._load_index()
            story_id = index["nfc_to_story"].get(nfc_uid)
            if story_id and story_id in index["stories"]:
                return Story(**index["stories"][story_id])
            return None

    def update_story(
        self,
        story_id: str,
        title: str | None = None,
        emoji: str | None = None,
        led_color: str | None = None,
        audio_file: str | None = None,
        cover_image: str | None = None,
        remove_cover: bool = False,
    ) -> Story | None:
        """Update a story's metadata and/or files.

        Args:
            story_id: Story ID to update
            title: New title (optional)
            emoji: New emoji (optional)
            led_color: New LED color (optional)
            audio_file: New audio filename (optional)
            cover_image: New cover filename (optional)
            remove_cover: If True, clear cover_image field

        Returns:
            Updated Story or None if story_id not found
        """
        with self._lock:
            index = self._load_index()

            # Check story exists
            if story_id not in index["stories"]:
                return None

            story_data = index["stories"][story_id]

            # Update only provided fields (if not None)
            if title is not None:
                story_data["title"] = title
            if emoji is not None:
                story_data["emoji"] = emoji
            if led_color is not None:
                story_data["led_color"] = led_color
            if audio_file is not None:
                story_data["audio_file"] = audio_file
            if cover_image is not None:
                story_data["cover_image"] = cover_image

            # Handle remove_cover flag
            if remove_cover:
                story_data["cover_image"] = None

            # Preserve nfc_uid and created_at (do not modify)
            # nfc_uid is already in story_data, created_at is already there

            self._save_index(index)
            return Story(**story_data)
