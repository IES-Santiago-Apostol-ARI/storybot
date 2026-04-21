"""Tests for cards CRUD API endpoints."""

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

    index_file = stories_dir / "stories.json"
    index_file.write_text(json.dumps({"version": 2, "stories": {}, "nfc_to_story": {}, "cards": {}}))

    manager = StoryManager()
    manager.CONTENT_DIR = stories_dir
    manager.INDEX_FILE = index_file

    return manager, stories_dir


@pytest.fixture
def client(temp_story_manager, monkeypatch):
    """Create test client with temporary stories directory."""
    story_manager, stories_dir = temp_story_manager

    monkeypatch.setattr(StoryManager, "CONTENT_DIR", stories_dir)
    monkeypatch.setattr(StoryManager, "INDEX_FILE", stories_dir / "stories.json")

    app.dependency_overrides = {}
    from app.dependencies import get_story_manager

    async def override_get_story_manager():
        return story_manager

    app.dependency_overrides[get_story_manager] = override_get_story_manager

    import app.routers.stories as stories_router_module
    original_path = stories_router_module.Path

    def mock_path(path_str):
        if path_str == "content/stories":
            return stories_dir
        return original_path(path_str)

    stories_router_module.Path = mock_path

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
        app.dependency_overrides = {}
        stories_router_module.Path = original_path
        main_module.Path = original_main_path


class TestPostCards:
    """Test POST /api/cards endpoint."""

    def test_post_parameter_card_returns_201(self, client: TestClient):
        """Register a parameter card."""
        response = client.post(
            "/api/cards",
            json={
                "uid": "11:22:33:44",
                "type": "parameter",
                "category": "character",
                "value": "dragon",
                "emoji": "🐉",
                "label": "Dragón",
            },
        )
        assert response.status_code == 201
        card = response.json()
        assert card["uid"] == "11:22:33:44"
        assert card["type"] == "parameter"
        assert card["category"] == "character"

    def test_post_go_card_returns_201(self, client: TestClient):
        """Register a go card."""
        response = client.post(
            "/api/cards",
            json={"uid": "99:88:77:66", "type": "go"},
        )
        assert response.status_code == 201
        card = response.json()
        assert card["uid"] == "99:88:77:66"
        assert card["type"] == "go"

    def test_post_parameter_card_missing_fields_returns_422(self, client: TestClient):
        """Parameter card without required fields returns 422."""
        response = client.post(
            "/api/cards",
            json={"uid": "11:22:33:44", "type": "parameter"},
        )
        assert response.status_code == 422

    def test_post_card_uid_conflict_with_story_returns_409(self, client: TestClient):
        """UID already assigned to a story returns 409."""
        # Create a story with NFC
        files = {"audio": ("audio.mp3", BytesIO(b"fake audio"), "audio/mpeg")}
        data = {"title": "Test", "emoji": "📖", "led_color": "#FF0000"}
        create_resp = client.post("/api/stories", files=files, data=data)
        story_id = create_resp.json()["id"]
        client.post(f"/api/stories/{story_id}/nfc", json={"nfc_uid": "AA:BB:CC:DD"})

        # Try to register same UID as parameter card
        response = client.post(
            "/api/cards",
            json={
                "uid": "AA:BB:CC:DD",
                "type": "parameter",
                "category": "character",
                "value": "dragon",
                "emoji": "🐉",
                "label": "Dragón",
            },
        )
        assert response.status_code == 409

    def test_post_card_uid_conflict_with_existing_card_returns_409(
        self, client: TestClient
    ):
        """UID already registered as a card returns 409."""
        client.post(
            "/api/cards",
            json={
                "uid": "11:22:33:44",
                "type": "parameter",
                "category": "character",
                "value": "dragon",
                "emoji": "🐉",
                "label": "Dragón",
            },
        )
        response = client.post(
            "/api/cards",
            json={
                "uid": "11:22:33:44",
                "type": "parameter",
                "category": "setting",
                "value": "forest",
                "emoji": "🌲",
                "label": "Bosque",
            },
        )
        assert response.status_code == 409


class TestGetCards:
    """Test GET /api/cards endpoint."""

    def test_get_cards_returns_all_cards(self, client: TestClient):
        """GET /api/cards returns all registered cards."""
        client.post(
            "/api/cards",
            json={
                "uid": "11:22:33:44",
                "type": "parameter",
                "category": "character",
                "value": "dragon",
                "emoji": "🐉",
                "label": "Dragón",
            },
        )
        client.post(
            "/api/cards",
            json={"uid": "99:88:77:66", "type": "go"},
        )

        response = client.get("/api/cards")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert len(body["cards"]) == 2

    def test_get_cards_filter_by_type_parameter(self, client: TestClient):
        """GET /api/cards?type=parameter returns only parameter cards."""
        client.post(
            "/api/cards",
            json={
                "uid": "11:22:33:44",
                "type": "parameter",
                "category": "character",
                "value": "dragon",
                "emoji": "🐉",
                "label": "Dragón",
            },
        )
        client.post(
            "/api/cards",
            json={"uid": "99:88:77:66", "type": "go"},
        )

        response = client.get("/api/cards?type=parameter")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["cards"][0]["type"] == "parameter"


class TestDeleteCards:
    """Test DELETE /api/cards/{uid} endpoint."""

    def test_delete_parameter_card_returns_204(self, client: TestClient):
        """DELETE a parameter card returns 204."""
        client.post(
            "/api/cards",
            json={
                "uid": "11:22:33:44",
                "type": "parameter",
                "category": "character",
                "value": "dragon",
                "emoji": "🐉",
                "label": "Dragón",
            },
        )
        response = client.delete("/api/cards/11:22:33:44")
        assert response.status_code == 204

    def test_delete_story_type_card_returns_400(self, client: TestClient):
        """DELETE a story-type card via cards endpoint returns 400."""
        files = {"audio": ("audio.mp3", BytesIO(b"fake audio"), "audio/mpeg")}
        data = {"title": "Test", "emoji": "📖", "led_color": "#FF0000"}
        create_resp = client.post("/api/stories", files=files, data=data)
        story_id = create_resp.json()["id"]
        client.post(f"/api/stories/{story_id}/nfc", json={"nfc_uid": "AA:BB:CC:DD"})

        response = client.delete("/api/cards/AA:BB:CC:DD")
        assert response.status_code == 400

    def test_delete_nonexistent_card_returns_404(self, client: TestClient):
        """DELETE a nonexistent card returns 404."""
        response = client.delete("/api/cards/UNKNOWN")
        assert response.status_code == 404
