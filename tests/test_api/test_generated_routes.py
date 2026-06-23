"""Wave 0 RED stubs for /api/generated CRUD (D-11) + path-traversal guard (T-16-01).

Plan 16-03 turns these GREEN.
"""

import json
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.story_manager import StoryManager


def _write_silent_wav(path: Path, frames: int = 22050) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(b"\x00\x00" * frames)


@pytest.fixture
def temp_story_manager(tmp_path):
    content = tmp_path / "content" / "stories"
    content.mkdir(parents=True)
    generated = tmp_path / "content" / "generated"
    generated.mkdir(parents=True)
    index = content / "stories.json"
    index.write_text(json.dumps({"version": 1, "stories": {}, "nfc_to_story": {}}))
    sm = StoryManager()
    sm.CONTENT_DIR = content
    sm.GENERATED_DIR = generated
    sm.INDEX_FILE = index
    return sm, generated


@pytest.fixture
def client(temp_story_manager, monkeypatch):
    sm, generated = temp_story_manager
    monkeypatch.setattr(StoryManager, "CONTENT_DIR", sm.CONTENT_DIR)
    monkeypatch.setattr(StoryManager, "GENERATED_DIR", sm.GENERATED_DIR)
    monkeypatch.setattr(StoryManager, "INDEX_FILE", sm.INDEX_FILE)
    from app.dependencies import get_story_manager
    app.dependency_overrides = {}

    async def override():
        return sm

    app.dependency_overrides[get_story_manager] = override
    with TestClient(app) as c:
        yield c, sm, generated
    app.dependency_overrides = {}


def _seed(generated: Path, story_id: str, n_segments: int = 2):
    d = generated / story_id
    audio = d / "audio"
    audio.mkdir(parents=True)
    for i in range(n_segments):
        _write_silent_wav(audio / f"{i:03d}.wav")
    (d / "story.json").write_text(json.dumps({
        "id": story_id,
        "text": "Había una vez un dragón",
        "parameters": [{"category": "personaje", "value": "dragón"}],
        "created_at": "2026-04-27T00:00:00Z",
    }))


class TestList:
    def test_returns_generated_stories(self, client):
        c, sm, generated = client
        _seed(generated, "11111111-1111-1111-1111-111111111111")
        _seed(generated, "22222222-2222-2222-2222-222222222222")
        resp = c.get("/api/generated")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["stories"]) == 2

    def test_empty_list(self, client):
        c, sm, generated = client
        resp = c.get("/api/generated")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


class TestDiscard:
    def test_delete_removes_dir(self, client):
        c, sm, generated = client
        sid = "11111111-1111-1111-1111-111111111111"
        _seed(generated, sid)
        resp = c.delete(f"/api/generated/{sid}")
        assert resp.status_code in (200, 204)
        assert not (generated / sid).exists()

    def test_delete_missing_returns_404(self, client):
        c, sm, generated = client
        resp = c.delete("/api/generated/99999999-9999-9999-9999-999999999999")
        assert resp.status_code == 404

    def test_path_traversal_rejected(self, client):
        # T-16-01: id=../../etc/passwd must be rejected at validation, not reach FS.
        c, sm, generated = client
        resp = c.delete("/api/generated/..%2F..%2Fetc%2Fpasswd")
        assert resp.status_code in (400, 404, 422)
        # /etc/passwd must still exist on the system
        assert Path("/etc/passwd").exists()


class TestPromote:
    def test_promote_creates_curated_story(self, client):
        c, sm, generated = client
        sid = "11111111-1111-1111-1111-111111111111"
        _seed(generated, sid, n_segments=2)
        resp = c.post(
            f"/api/generated/{sid}/promote",
            json={"title": "Mi cuento", "emoji": "🐉", "led_color": "#FF5733"},
        )
        assert resp.status_code == 201
        new_story = resp.json()
        assert new_story["title"] == "Mi cuento"
        assert new_story["emoji"] == "🐉"
        assert "id" in new_story

    def test_promote_invalid_uuid_rejected(self, client):
        c, sm, generated = client
        resp = c.post(
            "/api/generated/not-a-uuid/promote",
            json={"title": "T", "emoji": "🐉", "led_color": "#FF5733"},
        )
        assert resp.status_code in (400, 404, 422)

    def test_promote_path_traversal_rejected(self, client):
        c, sm, generated = client
        resp = c.post(
            "/api/generated/..%2F..%2Fetc/promote",
            json={"title": "T", "emoji": "🐉", "led_color": "#FF5733"},
        )
        assert resp.status_code in (400, 404, 422)

    def test_promote_missing_returns_404(self, client):
        c, sm, generated = client
        resp = c.post(
            "/api/generated/99999999-9999-9999-9999-999999999999/promote",
            json={"title": "T", "emoji": "🐉", "led_color": "#FF5733"},
        )
        assert resp.status_code == 404
