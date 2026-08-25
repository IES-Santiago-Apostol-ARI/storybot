"""Tests for AI sticker endpoints on uploaded (curated) stories."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.story_manager import StoryManager
from app.services.swap_orchestrator import LlamaRelaunchError, SwapOrchestrator

STORY_ID = "123e4567-e89b-12d3-a456-426614174000"


@pytest.fixture
def mock_story_manager():
    sm = MagicMock(spec=StoryManager)
    sm.get_story.return_value = SimpleNamespace(
        title="El dragón verde", cover_image="cover-orig.png"
    )
    app.state.story_manager = sm
    yield sm
    delattr(app.state, "story_manager")


@pytest.fixture
def mock_orchestrator():
    orch = AsyncMock(spec=SwapOrchestrator)
    orch.generate_cover_for_story.return_value = (
        Path("/tmp/cover-preview.png"),
        Path("/tmp/cover-print.png"),
        12.3,
    )
    app.state.swap_orchestrator = orch
    yield orch
    delattr(app.state, "swap_orchestrator")


@pytest.fixture
def ai_enabled():
    app.state.ai_enabled = True
    yield
    delattr(app.state, "ai_enabled")


def _setup_generated_dir(tmp_path):
    from app.routers import stickers

    generated_dir = tmp_path / "generated"
    generated_dir.mkdir(parents=True)
    original = getattr(stickers, "GENERATED_DIR", None)
    stickers.GENERATED_DIR = generated_dir
    return generated_dir, original


def _restore_generated_dir(original):
    from app.routers import stickers

    if original is not None:
        stickers.GENERATED_DIR = original
    else:
        delattr(stickers, "GENERATED_DIR")


def _make_cover_files(generated_dir, story_id=STORY_ID, mtime=None):
    story_dir = generated_dir / story_id
    story_dir.mkdir(parents=True, exist_ok=True)
    (story_dir / "cover-preview.png").write_bytes(b"png")
    print_png = story_dir / "cover-print.png"
    print_png.write_bytes(b"png")
    if mtime is not None:
        os.utime(print_png, (mtime, mtime))
    return story_dir


def _events(text):
    return [
        json.loads(line[6:]) for line in text.split("\n") if line.startswith("data: ")
    ]


def _failed_reason(text):
    for e in _events(text):
        if "sticker_failed" in e:
            return e["sticker_failed"]["reason"]
    return None


class TestGetSticker:
    """GET /api/stories/{story_id}/sticker."""

    def test_invalid_uuid_400(self, mock_story_manager):
        client = TestClient(app)
        resp = client.get("/api/stories/not-a-uuid/sticker")
        assert resp.status_code == 400

    def test_missing_story_404(self, mock_story_manager, tmp_path):
        mock_story_manager.get_story.return_value = None
        generated_dir, original = _setup_generated_dir(tmp_path)
        try:
            client = TestClient(app)
            resp = client.get(f"/api/stories/{STORY_ID}/sticker")
        finally:
            _restore_generated_dir(original)
        assert resp.status_code == 404

    def test_missing_print_png_404(self, mock_story_manager, tmp_path):
        generated_dir, original = _setup_generated_dir(tmp_path)
        try:
            story_dir = generated_dir / STORY_ID
            story_dir.mkdir()
            (story_dir / "cover-preview.png").write_bytes(b"png")
            client = TestClient(app)
            resp = client.get(f"/api/stories/{STORY_ID}/sticker")
        finally:
            _restore_generated_dir(original)
        assert resp.status_code == 404

    def test_happy_path_200(self, mock_story_manager, tmp_path):
        mtime = 1750000000.0
        generated_dir, original = _setup_generated_dir(tmp_path)
        try:
            _make_cover_files(generated_dir, mtime=mtime)
            client = TestClient(app)
            resp = client.get(f"/api/stories/{STORY_ID}/sticker")
        finally:
            _restore_generated_dir(original)
        assert resp.status_code == 200
        expected_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
        assert resp.json() == {
            "preview_url": f"/static/generated/{STORY_ID}/cover-preview.png",
            "print_url": f"/static/generated/{STORY_ID}/cover-print.png",
            "generated_at": expected_at,
        }


class TestPostSticker:
    """POST /api/stories/{story_id}/sticker (SSE)."""

    def test_ai_disabled_503(self, mock_story_manager, mock_orchestrator):
        app.state.ai_enabled = False
        try:
            client = TestClient(app)
            resp = client.post(f"/api/stories/{STORY_ID}/sticker", json={})
        finally:
            delattr(app.state, "ai_enabled")
        assert resp.status_code == 503
        assert resp.json() == {"error": "AI not available on this device"}

    def test_no_orchestrator_503(self, mock_story_manager, ai_enabled):
        if hasattr(app.state, "swap_orchestrator"):
            delattr(app.state, "swap_orchestrator")
        client = TestClient(app)
        resp = client.post(f"/api/stories/{STORY_ID}/sticker", json={})
        assert resp.status_code == 503
        assert resp.json() == {"error": "cover generation unavailable"}

    def test_invalid_uuid_400(self, mock_story_manager, mock_orchestrator, ai_enabled):
        client = TestClient(app)
        resp = client.post("/api/stories/bad-id/sticker", json={})
        assert resp.status_code == 400

    def test_missing_story_404(self, mock_story_manager, mock_orchestrator, ai_enabled):
        mock_story_manager.get_story.return_value = None
        client = TestClient(app)
        resp = client.post(f"/api/stories/{STORY_ID}/sticker", json={})
        assert resp.status_code == 404

    def test_happy_path_sse(self, mock_story_manager, mock_orchestrator, ai_enabled):
        client = TestClient(app)
        resp = client.post(f"/api/stories/{STORY_ID}/sticker", json={})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = _events(resp.text)
        names = [next(iter(e)) for e in events]
        assert "sticker_started" in names
        assert "sticker_ready" in names
        assert names.index("sticker_started") < names.index("sticker_ready")
        ready = next(e["sticker_ready"] for e in events if "sticker_ready" in e)
        assert ready["preview_url"] == (
            f"/static/generated/{STORY_ID}/cover-preview.png"
        )
        assert ready["print_url"] == f"/static/generated/{STORY_ID}/cover-print.png"
        assert ready["gen_seconds"] == 12.3

    def test_orchestrator_none_failed(
        self, mock_story_manager, mock_orchestrator, ai_enabled
    ):
        mock_orchestrator.generate_cover_for_story.return_value = (None, None, None)
        client = TestClient(app)
        resp = client.post(f"/api/stories/{STORY_ID}/sticker", json={})
        assert resp.status_code == 200
        assert _failed_reason(resp.text) == "orchestrator returned None"

    def test_llama_relaunch_failed(
        self, mock_story_manager, mock_orchestrator, ai_enabled
    ):
        mock_orchestrator.generate_cover_for_story.side_effect = LlamaRelaunchError(
            "boom"
        )
        client = TestClient(app)
        resp = client.post(f"/api/stories/{STORY_ID}/sticker", json={})
        assert resp.status_code == 200
        assert _failed_reason(resp.text) == "llama_relaunch_failed"

    def test_generic_exception_failed(
        self, mock_story_manager, mock_orchestrator, ai_enabled
    ):
        mock_orchestrator.generate_cover_for_story.side_effect = RuntimeError("boom")
        client = TestClient(app)
        resp = client.post(f"/api/stories/{STORY_ID}/sticker", json={})
        assert resp.status_code == 200
        assert _failed_reason(resp.text) == "RuntimeError"

    def test_hint_used_in_prompt(
        self, mock_story_manager, mock_orchestrator, ai_enabled
    ):
        client = TestClient(app)
        resp = client.post(
            f"/api/stories/{STORY_ID}/sticker", json={"hint": "un dragón azul"}
        )
        assert resp.status_code == 200
        args = mock_orchestrator.generate_cover_for_story.call_args[0]
        assert args[0] == STORY_ID
        assert "dragón azul" in args[1]

    def test_title_used_without_hint(
        self, mock_story_manager, mock_orchestrator, ai_enabled
    ):
        client = TestClient(app)
        resp = client.post(f"/api/stories/{STORY_ID}/sticker", json={})
        assert resp.status_code == 200
        args = mock_orchestrator.generate_cover_for_story.call_args[0]
        assert "El dragón verde" in args[1]

    def test_no_cover_image_side_effects(
        self, mock_story_manager, mock_orchestrator, ai_enabled
    ):
        """CRITICAL REGRESSION: the sticker never touches the story's own cover."""
        client = TestClient(app)
        resp = client.post(f"/api/stories/{STORY_ID}/sticker", json={})
        assert resp.status_code == 200
        assert "sticker_ready" in resp.text
        mock_story_manager.update_story.assert_not_called()
        mock_story_manager.attach_cover.assert_not_called()
        story = mock_story_manager.get_story.return_value
        assert story.cover_image == "cover-orig.png"
