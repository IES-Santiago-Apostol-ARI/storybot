"""Tests for static page serving (admin panel and children's kiosk)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """Create test client with lifespan context."""
    with TestClient(app) as c:
        yield c


class TestStaticPageServing:
    """Smoke tests verifying static HTML pages are served correctly."""

    def test_admin_panel_returns_html(self, client: TestClient):
        """GET /admin/ returns 200 with HTML content."""
        response = client.get("/admin/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    def test_children_kiosk_returns_html(self, client: TestClient):
        """GET /children/ returns 200 with HTML content."""
        response = client.get("/children/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
