"""Wave 0 RED stubs for /api/printer/print (D-18) + path-traversal guard (T-16-02).

Plan 16-04 turns these GREEN.
"""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    p = AsyncMock()
    p.is_mock = True
    with TestClient(app) as c:
        # Override the lifespan-created printer with our mock.
        app.state.printer = p
        yield c, p


class TestPrintRoute:
    def test_happy_path_under_content_generated(self, client, tmp_path, monkeypatch):
        c, printer = client
        # The route validates that path resolves under content/generated/ or content/stories/.
        # For the test, create a real PNG under the actual content/ root.
        target = Path("content/generated/test-uuid-print/cover-print.png")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\x89PNG\r\n\x1a\n")
        try:
            resp = c.post("/api/printer/print", json={"path": str(target)})
            assert resp.status_code == 200
            body = resp.json()
            assert body.get("ok") is True
            printer.print_sticker.assert_awaited_once()
        finally:
            if target.exists():
                target.unlink()
            if target.parent.exists():
                target.parent.rmdir()

    def test_missing_file_returns_400(self, client):
        c, _ = client
        resp = c.post(
            "/api/printer/print",
            json={"path": "content/generated/does-not-exist/cover-print.png"},
        )
        assert resp.status_code == 400

    def test_path_traversal_outside_content_rejected(self, client):
        # T-16-02: reject anything outside content/generated/ or content/stories/.
        c, _ = client
        resp = c.post("/api/printer/print", json={"path": "/etc/passwd"})
        assert resp.status_code == 400

    def test_dotdot_traversal_rejected(self, client):
        c, _ = client
        resp = c.post(
            "/api/printer/print",
            json={"path": "content/generated/../../etc/passwd"},
        )
        assert resp.status_code == 400
