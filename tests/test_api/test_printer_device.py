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


class _FakeBt:
    def __init__(self, pair_ok=True):
        self.pair_ok, self.paired, self.forgotten = pair_ok, [], []

    async def pair_printer(self, mac):
        self.paired.append(mac)
        return {"ok": True} if self.pair_ok else {"ok": False, "error": "DBusError"}

    async def forget(self, mac):
        self.forgotten.append(mac)
        return {"ok": True}


class TestPrinterReplace:
    """An unpaired printer refuses the RFCOMM print socket (EACCES), so Usar
    must pair the new unit and unpair the one it replaces."""

    def _put(self, c, monkeypatch, bt, mac="44:f7:9f:48:a5:d0"):
        monkeypatch.setattr("app.routers.printer.create_bt_manager", lambda: bt)
        return c.put("/api/printer/device", json={"mac": mac, "name": "QL-820NWB2824"})

    def test_pairs_new_and_forgets_old(self, client, monkeypatch):
        c, _ = client
        bt = _FakeBt()
        assert self._put(c, monkeypatch, bt).status_code == 200
        assert bt.paired == ["44:F7:9F:48:A5:D0"]
        assert bt.forgotten == ["04:68:74:2F:17:5C"]
        assert get_settings().printer_bt_address == "44:F7:9F:48:A5:D0"

    def test_same_printer_is_not_forgotten(self, client, monkeypatch):
        c, _ = client
        bt = _FakeBt()
        assert self._put(c, monkeypatch, bt, mac="04:68:74:2f:17:5c").status_code == 200
        assert bt.forgotten == []

    def test_pair_failure_keeps_old_printer(self, client, monkeypatch):
        c, cfg = client
        bt = _FakeBt(pair_ok=False)
        assert self._put(c, monkeypatch, bt).status_code == 502
        assert bt.forgotten == []
        assert not cfg.exists()
        assert get_settings().printer_bt_address == "04:68:74:2F:17:5C"
