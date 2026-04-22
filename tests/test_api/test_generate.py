"""Tests for generate API endpoints."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.story_generator import StoryGenerator


@pytest.fixture
def mock_story_generator():
    """Create a mock StoryGenerator and attach to app state."""
    sg = MagicMock(spec=StoryGenerator)
    app.state.story_generator = sg
    yield sg
    delattr(app.state, "story_generator")


@pytest.fixture
def client(mock_story_generator):
    """Test client with mock story generator."""
    return TestClient(app)


class TestGenerateStory:
    def test_generate_returns_sse(self, client, mock_story_generator):
        mock_story_generator.generate_story.return_value = iter(
            [
                {"text": "Hola", "done": False},
                {"text": None, "done": True},
            ]
        )

        resp = client.post(
            "/api/generate/story",
            json={"parameters": [{"category": "personaje", "value": "dragón"}]},
        )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        lines = [l for l in resp.text.strip().split("\n") if l.startswith("data: ")]
        assert len(lines) >= 2
        first = json.loads(lines[0][6:])
        assert first["text"] == "Hola"
        assert first["done"] is False

    def test_generate_empty_params_returns_400(self, client):
        resp = client.post(
            "/api/generate/story", json={"parameters": []}
        )
        assert resp.status_code == 400

    def test_generate_error_streams_error(self, client, mock_story_generator):
        mock_story_generator.generate_story.return_value = iter(
            [{"error": "llama-server no disponible", "done": True}]
        )

        resp = client.post(
            "/api/generate/story",
            json={"parameters": [{"category": "personaje", "value": "robot"}]},
        )

        assert resp.status_code == 200
        lines = [l for l in resp.text.strip().split("\n") if l.startswith("data: ")]
        first = json.loads(lines[0][6:])
        assert "error" in first
        assert first["done"] is True

    def test_generate_saves_story(self, client, mock_story_generator, tmp_path):
        mock_story_generator.generate_story.return_value = iter(
            [
                {"text": "Había ", "done": False},
                {"text": "una vez.", "done": False},
                {"text": None, "done": True},
            ]
        )

        generated_dir = tmp_path / "content" / "generated"
        generated_dir.mkdir(parents=True)

        from app.routers import generate as gen_module

        original_dir = getattr(gen_module, "GENERATED_DIR", None)
        gen_module.GENERATED_DIR = generated_dir

        try:
            resp = client.post(
                "/api/generate/story",
                json={
                    "parameters": [
                        {"category": "personaje", "value": "gato"},
                        {"category": "lugar", "value": "jardín"},
                    ]
                },
            )
        finally:
            if original_dir is not None:
                gen_module.GENERATED_DIR = original_dir
            else:
                delattr(gen_module, "GENERATED_DIR")

        assert resp.status_code == 200

        saved = list(generated_dir.glob("*/story.json"))
        assert len(saved) == 1

        data = json.loads(saved[0].read_text())
        assert data["text"] == "Había una vez."
        assert len(data["parameters"]) == 2
        assert "created_at" in data
