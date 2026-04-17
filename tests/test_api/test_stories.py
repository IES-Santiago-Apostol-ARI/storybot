"""Tests for Story API endpoints."""

import json
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.story_manager import StoryManager


@pytest.fixture
def temp_story_manager(tmp_path):
    """Create a StoryManager with temporary directory."""
    stories_dir = tmp_path / "content" / "stories"
    stories_dir.mkdir(parents=True)

    # Create empty stories index
    index_file = stories_dir / "stories.json"
    index_file.write_text(json.dumps({"version": 1, "stories": {}, "nfc_to_story": {}}))

    # Create StoryManager with temp directory
    manager = StoryManager()
    manager.CONTENT_DIR = stories_dir
    manager.INDEX_FILE = index_file

    return manager, stories_dir


@pytest.fixture
def client(temp_story_manager, monkeypatch):
    """Create test client with temporary stories directory."""
    story_manager, stories_dir = temp_story_manager

    # Patch StoryManager class attributes before app loads
    monkeypatch.setattr(StoryManager, "CONTENT_DIR", stories_dir)
    monkeypatch.setattr(StoryManager, "INDEX_FILE", stories_dir / "stories.json")

    # Override the app dependency to use our temp story manager
    app.dependency_overrides = {}
    from app.dependencies import get_story_manager

    async def override_get_story_manager():
        return story_manager

    app.dependency_overrides[get_story_manager] = override_get_story_manager

    # Also need to patch the hardcoded Path("content/stories") in the router
    # We'll do this by replacing the Path function temporarily in the stories router module
    import app.routers.stories as stories_router_module
    original_path = stories_router_module.Path

    def mock_path(path_str):
        if path_str == "content/stories":
            return stories_dir
        return original_path(path_str)

    stories_router_module.Path = mock_path

    # Also patch Path in main.py for the lifespan and static file mounting
    import app.main as main_module
    original_main_path = main_module.Path

    def mock_main_path(path_str):
        if path_str == "content/stories":
            return stories_dir
        return original_main_path(path_str)

    main_module.Path = mock_main_path

    try:
        with TestClient(app) as c:
            yield c
    finally:
        # Clean up
        app.dependency_overrides = {}
        stories_router_module.Path = original_path
        main_module.Path = original_main_path


class TestPostStories:
    """Test POST /api/stories endpoint."""

    def test_post_stories_with_multipart_returns_201(self, client: TestClient, tmp_path):
        """Test POST /api/stories with multipart form returns 201 with Story."""
        # Create multipart form data
        audio_content = b"fake audio data"
        files = {
            "audio": ("audio.mp3", BytesIO(audio_content), "audio/mpeg")
        }
        data = {
            "title": "Test Story",
            "emoji": "📚",
            "led_color": "#FF5733",
        }

        response = client.post("/api/stories", files=files, data=data)

        assert response.status_code == 201
        story = response.json()
        assert "id" in story
        assert story["title"] == "Test Story"
        assert story["emoji"] == "📚"
        assert story["led_color"] == "#FF5733"
        assert "audio_file" in story
        assert story["audio_file"] == "audio.mp3"
        assert story["nfc_uid"] is None
        assert story["cover_image"] is None
        assert "created_at" in story

    def test_post_stories_without_audio_returns_422(self, client: TestClient):
        """Test POST /api/stories without audio returns 422 (FastAPI validation)."""
        data = {
            "title": "Test Story",
            "emoji": "📚",
            "led_color": "#FF5733",
        }

        response = client.post("/api/stories", data=data)

        # FastAPI returns 422 for missing required form fields
        assert response.status_code == 422

    def test_post_stories_with_invalid_audio_type_returns_400(self, client: TestClient):
        """Test POST /api/stories with invalid audio type returns 400."""
        files = {
            "audio": ("document.pdf", BytesIO(b"fake pdf"), "application/pdf")
        }
        data = {
            "title": "Test Story",
            "emoji": "📚",
            "led_color": "#FF5733",
        }

        response = client.post("/api/stories", files=files, data=data)

        assert response.status_code == 400
        assert "audio" in response.json()["detail"].lower()

    def test_post_stories_with_cover_image_saves_cover(self, client: TestClient):
        """Test POST /api/stories with cover image saves cover file."""
        files = {
            "audio": ("audio.mp3", BytesIO(b"fake audio"), "audio/mpeg"),
            "cover": ("cover.jpg", BytesIO(b"fake image"), "image/jpeg"),
        }
        data = {
            "title": "Test Story",
            "emoji": "📚",
            "led_color": "#FF5733",
        }

        response = client.post("/api/stories", files=files, data=data)

        assert response.status_code == 201
        story = response.json()
        assert story["cover_image"] == "cover.jpg"


class TestGetStories:
    """Test GET /api/stories endpoint."""

    def test_get_stories_returns_story_list(self, client: TestClient):
        """Test GET /api/stories returns StoryList."""
        # First create a story
        files = {
            "audio": ("audio.mp3", BytesIO(b"fake audio"), "audio/mpeg")
        }
        data = {
            "title": "Test Story",
            "emoji": "📚",
            "led_color": "#FF5733",
        }
        client.post("/api/stories", files=files, data=data)

        # Now list stories
        response = client.get("/api/stories")

        assert response.status_code == 200
        stories = response.json()
        assert "stories" in stories
        assert "total" in stories
        assert stories["total"] == 1
        assert len(stories["stories"]) == 1
        assert stories["stories"][0]["title"] == "Test Story"

    def test_get_stories_empty_returns_empty_list(self, client: TestClient):
        """Test GET /api/stories returns empty list when no stories."""
        response = client.get("/api/stories")

        assert response.status_code == 200
        stories = response.json()
        assert stories["stories"] == []
        assert stories["total"] == 0


class TestGetStoryById:
    """Test GET /api/stories/{id} endpoint."""

    def test_get_story_by_id_returns_story(self, client: TestClient):
        """Test GET /api/stories/{id} returns Story."""
        # First create a story
        files = {
            "audio": ("audio.mp3", BytesIO(b"fake audio"), "audio/mpeg")
        }
        data = {
            "title": "Test Story",
            "emoji": "📚",
            "led_color": "#FF5733",
        }
        create_response = client.post("/api/stories", files=files, data=data)
        story_id = create_response.json()["id"]

        # Get story by ID
        response = client.get(f"/api/stories/{story_id}")

        assert response.status_code == 200
        story = response.json()
        assert story["id"] == story_id
        assert story["title"] == "Test Story"

    def test_get_story_by_invalid_id_returns_404(self, client: TestClient):
        """Test GET /api/stories/{id} with invalid ID returns 404."""
        response = client.get("/api/stories/non-existent-id")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestDeleteStory:
    """Test DELETE /api/stories/{id} endpoint."""

    def test_delete_story_returns_204(self, client: TestClient):
        """Test DELETE /api/stories/{id} returns 204."""
        # First create a story
        files = {
            "audio": ("audio.mp3", BytesIO(b"fake audio"), "audio/mpeg")
        }
        data = {
            "title": "Test Story",
            "emoji": "📚",
            "led_color": "#FF5733",
        }
        create_response = client.post("/api/stories", files=files, data=data)
        story_id = create_response.json()["id"]

        # Delete story
        response = client.delete(f"/api/stories/{story_id}")

        assert response.status_code == 204

        # Verify it's deleted
        get_response = client.get(f"/api/stories/{story_id}")
        assert get_response.status_code == 404

    def test_delete_story_with_invalid_id_returns_404(self, client: TestClient):
        """Test DELETE /api/stories/{id} with invalid ID returns 404."""
        response = client.delete("/api/stories/non-existent-id")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestNFCAssignment:
    """Test NFC assignment endpoints."""

    def test_post_nfc_to_story_assigns_card(self, client: TestClient):
        """Test POST /api/stories/{id}/nfc assigns NFC card to story."""
        # First create a story
        files = {
            "audio": ("audio.mp3", BytesIO(b"fake audio"), "audio/mpeg")
        }
        data = {
            "title": "Test Story",
            "emoji": "📚",
            "led_color": "#FF5733",
        }
        create_response = client.post("/api/stories", files=files, data=data)
        story_id = create_response.json()["id"]

        # Assign NFC card
        nfc_data = {"nfc_uid": "04:A3:5B:C2:D4:30"}
        response = client.post(f"/api/stories/{story_id}/nfc", json=nfc_data)

        assert response.status_code == 200
        story = response.json()
        assert story["id"] == story_id
        assert story["nfc_uid"] == "04:A3:5B:C2:D4:30"

    def test_post_nfc_to_invalid_story_returns_404(self, client: TestClient):
        """Test POST /api/stories/{id}/nfc with invalid story_id returns 404."""
        nfc_data = {"nfc_uid": "04:A3:5B:C2:D4:30"}
        response = client.post("/api/stories/non-existent-id/nfc", json=nfc_data)

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_get_story_by_nfc_returns_story(self, client: TestClient):
        """Test GET /api/stories/nfc/{uid} returns Story for valid mapping."""
        # First create a story and assign NFC
        files = {
            "audio": ("audio.mp3", BytesIO(b"fake audio"), "audio/mpeg")
        }
        data = {
            "title": "Test Story",
            "emoji": "📚",
            "led_color": "#FF5733",
        }
        create_response = client.post("/api/stories", files=files, data=data)
        story_id = create_response.json()["id"]

        nfc_uid = "04:A3:5B:C2:D4:30"
        nfc_data = {"nfc_uid": nfc_uid}
        client.post(f"/api/stories/{story_id}/nfc", json=nfc_data)

        # Get story by NFC
        response = client.get(f"/api/stories/nfc/{nfc_uid}")

        assert response.status_code == 200
        story = response.json()
        assert story["id"] == story_id
        assert story["title"] == "Test Story"
        assert story["nfc_uid"] == nfc_uid

    def test_get_story_by_unknown_nfc_returns_404(self, client: TestClient):
        """Test GET /api/stories/nfc/{uid} with unknown UID returns 404."""
        response = client.get("/api/stories/nfc/04:AA:BB:CC:DD:EE")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower() or "no story" in response.json()["detail"].lower()

    def test_assigning_same_nfc_to_different_story_updates_mapping(self, client: TestClient):
        """Test assigning same NFC to different story updates mapping (1:1)."""
        # Create two stories
        files = {
            "audio": ("audio.mp3", BytesIO(b"fake audio"), "audio/mpeg")
        }
        data1 = {
            "title": "Story 1",
            "emoji": "📚",
            "led_color": "#FF5733",
        }
        data2 = {
            "title": "Story 2",
            "emoji": "🎮",
            "led_color": "#00FF00",
        }

        response1 = client.post("/api/stories", files=files, data=data1)
        story1_id = response1.json()["id"]

        response2 = client.post("/api/stories", files=files, data=data2)
        story2_id = response2.json()["id"]

        # Assign NFC to first story
        nfc_uid = "04:A3:5B:C2:D4:30"
        nfc_data = {"nfc_uid": nfc_uid}
        client.post(f"/api/stories/{story1_id}/nfc", json=nfc_data)

        # Reassign NFC to second story
        client.post(f"/api/stories/{story2_id}/nfc", json=nfc_data)

        # Verify NFC now points to second story
        response = client.get(f"/api/stories/nfc/{nfc_uid}")
        assert response.status_code == 200
        story = response.json()
        assert story["id"] == story2_id
        assert story["title"] == "Story 2"


class TestPutStory:
    """Test PUT /api/stories/{id} endpoint."""

    def test_put_story_with_valid_data_returns_200(self, client: TestClient):
        """Test PUT /api/stories/{id} with valid data returns 200 with updated Story."""
        # First create a story
        files = {
            "audio": ("audio.mp3", BytesIO(b"fake audio"), "audio/mpeg")
        }
        data = {
            "title": "Original Title",
            "emoji": "📚",
            "led_color": "#FF5733",
        }
        create_response = client.post("/api/stories", files=files, data=data)
        story_id = create_response.json()["id"]

        # Update story
        update_data = {
            "title": "Updated Title",
            "emoji": "🎉",
            "led_color": "#00FF00",
        }
        response = client.put(f"/api/stories/{story_id}", data=update_data)

        assert response.status_code == 200
        story = response.json()
        assert story["id"] == story_id
        assert story["title"] == "Updated Title"
        assert story["emoji"] == "🎉"
        assert story["led_color"] == "#00FF00"
        assert story["audio_file"] == "audio.mp3"

    def test_put_story_with_invalid_id_returns_404(self, client: TestClient):
        """Test PUT /api/stories/{id} with invalid story_id returns 404."""
        data = {
            "title": "Updated Title",
            "emoji": "🎉",
            "led_color": "#00FF00",
        }
        response = client.put("/api/stories/non-existent-id", data=data)

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_put_story_with_new_audio_file_replaces_audio(self, client: TestClient, tmp_path):
        """Test PUT with new audio file replaces old audio."""
        # First create a story
        files = {
            "audio": ("audio.mp3", BytesIO(b"original audio"), "audio/mpeg")
        }
        data = {
            "title": "Test Story",
            "emoji": "📚",
            "led_color": "#FF5733",
        }
        create_response = client.post("/api/stories", files=files, data=data)
        story_id = create_response.json()["id"]

        # Update with new audio
        new_files = {
            "audio": ("audio.wav", BytesIO(b"new audio"), "audio/wav")
        }
        update_data = {
            "title": "Test Story",
            "emoji": "📚",
            "led_color": "#FF5733",
        }
        response = client.put(f"/api/stories/{story_id}", files=new_files, data=update_data)

        assert response.status_code == 200
        story = response.json()
        assert story["audio_file"] == "audio.wav"

    def test_put_story_with_new_cover_file_replaces_cover(self, client: TestClient, tmp_path):
        """Test PUT with new cover file replaces old cover."""
        # First create a story with cover
        files = {
            "audio": ("audio.mp3", BytesIO(b"fake audio"), "audio/mpeg"),
            "cover": ("cover.jpg", BytesIO(b"original cover"), "image/jpeg"),
        }
        data = {
            "title": "Test Story",
            "emoji": "📚",
            "led_color": "#FF5733",
        }
        create_response = client.post("/api/stories", files=files, data=data)
        story_id = create_response.json()["id"]

        # Update with new cover
        new_files = {
            "cover": ("cover.png", BytesIO(b"new cover"), "image/png"),
        }
        update_data = {
            "title": "Test Story",
            "emoji": "📚",
            "led_color": "#FF5733",
        }
        response = client.put(f"/api/stories/{story_id}", files=new_files, data=update_data)

        assert response.status_code == 200
        story = response.json()
        assert story["cover_image"] == "cover.png"

    def test_put_story_with_remove_cover_clears_cover(self, client: TestClient, tmp_path):
        """Test PUT with remove_cover=true clears cover_image."""
        # First create a story with cover
        files = {
            "audio": ("audio.mp3", BytesIO(b"fake audio"), "audio/mpeg"),
            "cover": ("cover.jpg", BytesIO(b"fake cover"), "image/jpeg"),
        }
        data = {
            "title": "Test Story",
            "emoji": "📚",
            "led_color": "#FF5733",
        }
        create_response = client.post("/api/stories", files=files, data=data)
        story_id = create_response.json()["id"]

        # Update with remove_cover=true
        update_data = {
            "title": "Test Story",
            "emoji": "📚",
            "led_color": "#FF5733",
            "remove_cover": "true",
        }
        response = client.put(f"/api/stories/{story_id}", data=update_data)

        assert response.status_code == 200
        story = response.json()
        assert story["cover_image"] is None

    def test_put_story_without_audio_preserves_existing_audio(self, client: TestClient):
        """Test PUT without audio file preserves existing audio."""
        # First create a story
        files = {
            "audio": ("audio.mp3", BytesIO(b"fake audio"), "audio/mpeg")
        }
        data = {
            "title": "Test Story",
            "emoji": "📚",
            "led_color": "#FF5733",
        }
        create_response = client.post("/api/stories", files=files, data=data)
        story_id = create_response.json()["id"]
        original_audio = create_response.json()["audio_file"]

        # Update without providing audio
        update_data = {
            "title": "Updated Title",
            "emoji": "📚",
            "led_color": "#FF5733",
        }
        response = client.put(f"/api/stories/{story_id}", data=update_data)

        assert response.status_code == 200
        story = response.json()
        assert story["audio_file"] == original_audio

    def test_put_story_without_cover_preserves_existing_cover(self, client: TestClient):
        """Test PUT without cover file preserves existing cover."""
        # First create a story with cover
        files = {
            "audio": ("audio.mp3", BytesIO(b"fake audio"), "audio/mpeg"),
            "cover": ("cover.jpg", BytesIO(b"fake cover"), "image/jpeg"),
        }
        data = {
            "title": "Test Story",
            "emoji": "📚",
            "led_color": "#FF5733",
        }
        create_response = client.post("/api/stories", files=files, data=data)
        story_id = create_response.json()["id"]
        original_cover = create_response.json()["cover_image"]

        # Update without providing cover
        update_data = {
            "title": "Updated Title",
            "emoji": "📚",
            "led_color": "#FF5733",
        }
        response = client.put(f"/api/stories/{story_id}", data=update_data)

        assert response.status_code == 200
        story = response.json()
        assert story["cover_image"] == original_cover

    def test_put_story_with_invalid_audio_type_returns_400(self, client: TestClient):
        """Test PUT /api/stories/{id} with invalid audio type returns 400."""
        files = {
            "audio": ("audio.mp3", BytesIO(b"fake audio"), "audio/mpeg")
        }
        data = {
            "title": "Test Story",
            "emoji": "📚",
            "led_color": "#FF5733",
        }
        create_response = client.post("/api/stories", files=files, data=data)
        story_id = create_response.json()["id"]

        new_files = {
            "audio": ("document.pdf", BytesIO(b"fake pdf"), "application/pdf")
        }
        update_data = {
            "title": "Test Story",
            "emoji": "📚",
            "led_color": "#FF5733",
        }
        response = client.put(f"/api/stories/{story_id}", files=new_files, data=update_data)

        assert response.status_code == 400
        assert "audio" in response.json()["detail"].lower()
