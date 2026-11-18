"""API responses must never be cached by the kiosk browser.

The Jetson boots offline with its clock at 1970 until time syncs. API
responses carried no Cache-Control, so Firefox applied heuristic caching to
them. With "now" earlier than the cached response's Date, a stale
``/api/stories`` (``{"stories": []}`` from before any story was saved) stayed
"fresh" forever and was never revalidated, so the kiosk showed an empty grid
even though stories existed.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_story_manager
from app.main import app
from app.services.story_manager import StoryManager


@pytest.fixture
def client(tmp_path, monkeypatch):
    stories_dir = tmp_path / "content" / "stories"
    stories_dir.mkdir(parents=True)
    index_file = stories_dir / "stories.json"
    index_file.write_text(json.dumps({"version": 1, "stories": {}, "nfc_to_story": {}}))
    monkeypatch.setattr(StoryManager, "CONTENT_DIR", stories_dir)
    monkeypatch.setattr(StoryManager, "INDEX_FILE", index_file)
    manager = StoryManager()

    async def override():
        return manager

    app.dependency_overrides[get_story_manager] = override
    yield TestClient(app)
    app.dependency_overrides.pop(get_story_manager, None)


@pytest.mark.parametrize("path", ["/api/stories", "/api/does-not-exist"])
def test_api_responses_are_not_cacheable(client, path):
    response = client.get(path)
    assert "no-store" in response.headers.get("cache-control", "")


def test_non_api_routes_keep_their_own_cache_policy(client):
    response = client.get("/children/")
    assert response.headers.get("cache-control") == "no-cache, must-revalidate"


@pytest.mark.parametrize(
    "path", ["/admin/", "/admin/script.js", "/admin/styles.css", "/admin/index.html"]
)
def test_admin_code_always_revalidates(client, path):
    # Plain StaticFiles left /admin heuristically cached: after a deploy the
    # browser ran the old script.js against the new index.html, so the new
    # "Buscar impresora" button had no click handler.
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-cache, must-revalidate"
