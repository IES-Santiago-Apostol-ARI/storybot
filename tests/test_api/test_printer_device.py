"""/api/printer/scan + /api/printer/device — choose the Bluetooth printer
from /admin (a replacement QL-820NWB only needs its address saved)."""

import json

import pytest
from fastapi.testclient import TestClient

import app.config as config_module
from app.config import ConfigManager, get_settings
from app.main import app


@pytest.fixture
def client(monkeypatch, tmp_path):
    # Never write the repo's content/config.json from a test.
    monkeypatch.setattr(
        config_module, "_manager", ConfigManager(tmp_path / "config.json")
    )
    with TestClient(app) as c:
        yield c, tmp_path / "config.json"


class TestPrinterScan:
    def test_scan_returns_printers(self, client):
        c, _ = client
        resp = c.get("/api/printer/scan")
        assert resp.status_code == 200
        data = resp.json()
        assert data and all(d["name"].startswith("QL-820NWB") for d in data)
        assert set(data[0]) == {"name", "mac", "rssi"}


class TestPrinterDevice:
    def test_get_returns_configured_printer(self, client):
        c, _ = client
        resp = c.get("/api/printer/device")
        assert resp.status_code == 200
        assert resp.json() == {"name": "QL-820NWB9000", "mac": "04:68:74:2F:17:5C"}

    def test_put_saves_new_printer(self, client):
        c, cfg = client
        resp = c.put(
            "/api/printer/device",
            json={"mac": "04:68:74:2F:17:5D", "name": "QL-820NWB1234"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert get_settings().printer_bt_address == "04:68:74:2F:17:5D"
        assert get_settings().printer_bt_name == "QL-820NWB1234"
        saved = json.loads(cfg.read_text())
        assert saved["printer_bt_address"] == "04:68:74:2F:17:5D"
        assert c.get("/api/printer/device").json()["mac"] == "04:68:74:2F:17:5D"

    def test_put_rejects_bad_mac(self, client):
        c, cfg = client
        resp = c.put("/api/printer/device", json={"mac": "not-a-mac", "name": "x"})
        assert resp.status_code == 422
        assert not cfg.exists()
