"""Story manager service for CRUD operations and NFC mapping."""

import json
import re
import shutil
import sys
import threading
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path

from app.models.story import Story, StoryCreate

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _is_valid_generated_id(story_id: str) -> bool:
    """Defense-in-depth: reject path-traversal characters in generated ids.

    The router layer enforces canonical UUID format for HTTP requests.
    This service-level guard prevents misuse from any call site by
    blocking ``..`` and ``/`` in the id string.
    """
    return ".." not in story_id and "/" not in story_id


class StoryManager:
    """Manager for story CRUD operations with JSON index persistence."""

    CONTENT_DIR = Path("content/stories")
    INDEX_FILE = CONTENT_DIR / "stories.json"
    GENERATED_DIR = Path("content/generated")

    def __init__(self) -> None:
        """Initialize StoryManager."""
        self._lock = threading.Lock()

    def _load_index(self) -> dict:
        """Load story index from JSON file.

        Returns:
            dict with keys: version, stories, nfc_to_story, cards
        """
        if not self.INDEX_FILE.exists():
            return {"version": 2, "stories": {}, "nfc_to_story": {}, "cards": {}}

        with open(self.INDEX_FILE, "r") as f:
            index = json.load(f)

        if index.get("version", 1) < 2:
            self._migrate_v1_to_v2(index)
        return index

    def _migrate_v1_to_v2(self, index: dict) -> None:
        """Migrate v1 index to v2 by building cards dict from nfc_to_story."""
        cards = {}
        for uid, story_id in index.get("nfc_to_story", {}).items():
            cards[uid] = {"uid": uid, "type": "story", "story_id": story_id}
        index["cards"] = cards
        index["version"] = 2
        self._save_index(index)

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
                index.setdefault("cards", {})[nfc_uid] = {
                    "uid": nfc_uid,
                    "type": "story",
                    "story_id": id,
                }

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
                index.get("cards", {}).pop(nfc_uid, None)

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
            if old_nfc_uid:
                index.get("cards", {}).pop(old_nfc_uid, None)

            # Update story with new NFC UID
            index["stories"][story_id]["nfc_uid"] = nfc_uid
            index["nfc_to_story"][nfc_uid] = story_id
            index.setdefault("cards", {})[nfc_uid] = {
                "uid": nfc_uid,
                "type": "story",
                "story_id": story_id,
            }

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

    def get_card(self, uid: str) -> dict | None:
        """Get a card by NFC UID.

        Args:
            uid: NFC card UID

        Returns:
            Card dict or None if not found
        """
        with self._lock:
            index = self._load_index()
            return index.get("cards", {}).get(uid)

    def create_card(self, card_data: dict) -> dict:
        """Register a new card (parameter or go type).

        Args:
            card_data: Card data with uid, type, and type-specific fields

        Returns:
            Created card dict

        Raises:
            ValueError: If uid is already registered
        """
        uid = card_data["uid"]
        with self._lock:
            index = self._load_index()

            if uid in index.get("nfc_to_story", {}):
                raise ValueError(f"UID {uid} already registered as story card")
            if uid in index.get("cards", {}):
                raise ValueError(f"UID {uid} already registered")

            index.setdefault("cards", {})[uid] = card_data
            self._save_index(index)
            return card_data

    def delete_card(self, uid: str) -> bool:
        """Delete a non-story card by UID.

        Args:
            uid: NFC card UID

        Returns:
            True if deleted, False if not found

        Raises:
            ValueError: If card is a story-type card (use delete_story instead)
        """
        with self._lock:
            index = self._load_index()

            card = index.get("cards", {}).get(uid)
            if card is None:
                return False
            if card.get("type") == "story":
                raise ValueError(
                    "Cannot delete story-type card via delete_card. Use delete_story."
                )

            del index["cards"][uid]
            self._save_index(index)
            return True

    def attach_cover(self, story_id: str, preview_path: str, print_path: str) -> None:
        """Add cover metadata to a generated story's story.json.

        Args:
            story_id: Story directory name under content/generated/.
            preview_path: Absolute path to cover-preview.png.
            print_path: Absolute path to cover-print.png.
        """
        generated_dir = self.GENERATED_DIR
        story_file = generated_dir / story_id / "story.json"

        if not story_file.exists():
            print(
                json.dumps(
                    {
                        "event": "cover_attach_orphan",
                        "story_id": story_id,
                    }
                ),
                file=sys.stderr,
            )
            return

        story_data = json.loads(story_file.read_text())
        story_data["cover"] = {
            "preview": "cover-preview.png",
            "print": "cover-print.png",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        tmp = story_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(story_data, ensure_ascii=False, indent=2))
        tmp.rename(story_file)

    def list_generated(self) -> list[dict]:
        """Return lightweight summaries for each generated story dir.

        Each summary has keys: id, text_preview (≤120 chars), parameters,
        created_at, cover (or None).  Directories without story.json are skipped.
        """
        out: list[dict] = []
        if not self.GENERATED_DIR.exists():
            return out
        for d in sorted(self.GENERATED_DIR.iterdir()):
            if not d.is_dir():
                continue
            sj = d / "story.json"
            if not sj.exists():
                continue
            try:
                data = json.loads(sj.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            out.append(
                {
                    "id": data.get("id", d.name),
                    "text_preview": (data.get("text", "") or "")[:120],
                    "parameters": data.get("parameters", []),
                    "created_at": data.get("created_at"),
                    "cover": data.get("cover"),
                }
            )
        return out

    def delete_generated(self, story_id: str) -> bool:
        """Recursively remove content/generated/<story_id>/.

        Returns True if removed, False if not found or id is unsafe.
        """
        if not _is_valid_generated_id(story_id):
            print(
                json.dumps({"event": "discard_invalid_id", "story_id": story_id}),
                file=sys.stderr,
            )
            return False
        target = self.GENERATED_DIR / story_id
        # Defense-in-depth path containment check.
        try:
            resolved = target.resolve()
            gdir_resolved = self.GENERATED_DIR.resolve()
            if hasattr(resolved, "is_relative_to"):
                if not resolved.is_relative_to(gdir_resolved):
                    return False
            else:
                if gdir_resolved not in resolved.parents and resolved != gdir_resolved:
                    return False
        except (OSError, ValueError):
            return False
        if not target.exists():
            return False
        shutil.rmtree(target)
        print(
            json.dumps({"event": "discard_complete", "story_id": story_id}),
            file=sys.stderr,
        )
        return True

    def promote_generated(
        self,
        generated_id: str,
        title: str,
        emoji: str,
        led_color: str,
    ) -> Story:
        """Promote a generated story into the curated library.

        Concatenates segment WAVs into a single mono 22050Hz 16-bit file,
        copies the cover (if present), registers via create_story, and
        deletes the generated directory on success.
        """
        if not _is_valid_generated_id(generated_id):
            raise ValueError(f"invalid generated id: {generated_id!r}")

        src_dir = self.GENERATED_DIR / generated_id
        if not src_dir.exists() or not (src_dir / "story.json").exists():
            raise FileNotFoundError(f"generated story {generated_id} not found")

        audio_dir = src_dir / "audio"
        segments = sorted(audio_dir.glob("*.wav")) if audio_dir.exists() else []
        if not segments:
            raise FileNotFoundError(f"no audio segments under {audio_dir}")

        # Verify all segments share params.
        params_ref = None
        with wave.open(str(segments[0]), "rb") as wf0:
            params_ref = (wf0.getnchannels(), wf0.getsampwidth(), wf0.getframerate())
        for seg in segments[1:]:
            with wave.open(str(seg), "rb") as wf:
                seg_params = (wf.getnchannels(), wf.getsampwidth(), wf.getframerate())
                if seg_params != params_ref:
                    print(
                        json.dumps(
                            {
                                "event": "promote_segment_format_mismatch",
                                "story_id": generated_id,
                                "segment": seg.name,
                            }
                        ),
                        file=sys.stderr,
                    )
                    raise ValueError(f"segment {seg.name} has incompatible WAV params")

        # Reserve the new curated id so we can write audio before create_story.
        new_id = str(uuid.uuid4())
        curated_dir = self.CONTENT_DIR / new_id
        curated_dir.mkdir(parents=True, exist_ok=True)

        audio_out = curated_dir / "narration.wav"
        with wave.open(str(audio_out), "wb") as out:
            out.setnchannels(params_ref[0])
            out.setsampwidth(params_ref[1])
            out.setframerate(params_ref[2])
            for seg in segments:
                with wave.open(str(seg), "rb") as wf:
                    out.writeframes(wf.readframes(wf.getnframes()))

        # Copy cover if present.
        cover_src = src_dir / "cover-preview.png"
        cover_image_field: str | None = None
        if cover_src.exists():
            cover_dst = curated_dir / "cover-preview.png"
            shutil.copy2(cover_src, cover_dst)
            cover_image_field = "cover-preview.png"

        print(
            json.dumps(
                {"event": "promote_started", "src": generated_id, "new_id": new_id}
            ),
            file=sys.stderr,
        )

        # Register in stories.json — create_story accepts explicit id.
        story = self.create_story(
            id=new_id,
            title=title,
            emoji=emoji,
            led_color=led_color,
            audio_file="narration.wav",
            cover_image=cover_image_field,
        )

        # Delete-on-promote.
        shutil.rmtree(src_dir)
        print(
            json.dumps(
                {
                    "event": "promote_complete",
                    "src": generated_id,
                    "new_id": story.id,
                }
            ),
            file=sys.stderr,
        )
        return story
