"""Tests for Bluetooth API endpoints — scan, last, status (Phase 26-03).

Mirrors tests/test_api/test_wifi.py's TestClient(app) + lifespan fixture pattern.
TESTING=1 is already global in conftest.py, so create_bt_manager() returns the
deterministic MockBtManager — no hardware needed.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(monkeypatch):
    """Create test client with lifespan context.

    Force AI enabled so the app boots fully (mirrors test_wifi.py fixture).
    TESTING=1 is already global in conftest → MockBtManager is returned by the
    factory automatically.
    """
    monkeypatch.setenv("STORYBOT_AI", "1")
    with TestClient(app) as c:
        yield c


class TestBtScan:
    """Test GET /api/bt/scan endpoint."""

    def test_scan_returns_200(self, client):
        """GET /api/bt/scan returns 200 status."""
        response = client.get("/api/bt/scan")
        assert response.status_code == 200

    def test_scan_returns_list(self, client):
        """GET /api/bt/scan returns a JSON list."""
        response = client.get("/api/bt/scan")
        data = response.json()
        assert isinstance(data, list)

    def test_scan_returns_audio_devices_with_name_mac_rssi(self, client):
        """Each scanned device has name, mac, rssi keys (BT-01/BT-07).

        MockBtManager returns 2 deterministic devices — assert at least one
        is present and each has the required fields.
        """
        response = client.get("/api/bt/scan")
        data = response.json()
        assert len(data) >= 1
        for device in data:
            assert "name" in device
            assert "mac" in device
            assert "rssi" in device  # may be None for cached, but key present

    def test_scan_returns_deterministic_mock_list(self, client):
        """Under TESTING the factory returns MockBtManager with the fixed list."""
        response = client.get("/api/bt/scan")
        data = response.json()
        # MockBtManager._MOCK_SCAN has 2 devices (D-10).
        assert len(data) == 2
        names = {d["name"] for d in data}
        assert "Mock JBL" in names
        assert "Mock Bose" in names

    def test_scan_rssi_is_strongest_first(self, client):
        """Devices are RSSI-sorted strongest-first (D-06)."""
        response = client.get("/api/bt/scan")
        data = response.json()
        rssis = [d["rssi"] for d in data if d["rssi"] is not None]
        assert rssis == sorted(rssis, reverse=True)


class TestBtLast:
    """Test GET /api/bt/last endpoint (BT-06/D-11)."""

    def test_last_returns_200(self, client):
        """GET /api/bt/last returns 200 status."""
        response = client.get("/api/bt/last")
        assert response.status_code == 200

    def test_last_returns_preseeded_speaker(self, client):
        """GET /api/bt/last returns the pre-seeded Mock speaker (D-11)."""
        response = client.get("/api/bt/last")
        data = response.json()
        # MockBtManager pre-seeds 'Mock JBL' / AA:BB:CC:00:11:22 (D-11).
        assert data is not None
        assert data["name"] == "Mock JBL"
        assert data["mac"] == "AA:BB:CC:00:11:22"

    def test_last_response_shape(self, client):
        """The last-speaker object has name + mac keys."""
        response = client.get("/api/bt/last")
        data = response.json()
        assert data is not None
        assert "name" in data
        assert "mac" in data


class TestBtStatus:
    """Test GET /api/bt/status endpoint."""

    def test_status_returns_200(self, client):
        """GET /api/bt/status returns 200 status."""
        response = client.get("/api/bt/status")
        assert response.status_code == 200

    def test_status_is_mock_under_testing(self, client):
        """Under TESTING, /api/bt/status reports is_mock=true."""
        response = client.get("/api/bt/status")
        data = response.json()
        assert data["is_mock"] is True

    def test_status_has_status_field(self, client):
        """/api/bt/status returns a status field."""
        response = client.get("/api/bt/status")
        data = response.json()
        assert "status" in data

    def test_status_platform_is_valid(self, client):
        """/api/bt/status returns platform ∈ {jetson, rpi, generic}."""
        response = client.get("/api/bt/status")
        data = response.json()
        assert "platform" in data
        assert data["platform"] in {"jetson", "rpi", "generic"}

    def test_status_has_adapter_present(self, client):
        """/api/bt/status returns adapter_present boolean."""
        response = client.get("/api/bt/status")
        data = response.json()
        assert "adapter_present" in data
        assert isinstance(data["adapter_present"], bool)


class TestBtRouterRegistration:
    """Test that BT router is registered and accessible."""

    def test_scan_endpoint_exists(self, client):
        """GET /api/bt/scan is registered (not 404)."""
        response = client.get("/api/bt/scan")
        assert response.status_code != 404

    def test_last_endpoint_exists(self, client):
        """GET /api/bt/last is registered (not 404)."""
        response = client.get("/api/bt/last")
        assert response.status_code != 404

    def test_status_endpoint_exists(self, client):
        """GET /api/bt/status is registered (not 404)."""
        response = client.get("/api/bt/status")
        assert response.status_code != 404


class TestBtPair:
    """POST /api/bt/pair (BT-02)."""

    def test_pair_returns_200_ok(self, client):
        """POST /api/bt/pair with a valid MAC+name → 200 {ok:true} under Mock."""
        response = client.post(
            "/api/bt/pair",
            json={"mac": "AA:BB:CC:00:11:22", "name": "JBL"},
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True}

    def test_pair_invalid_mac_returns_422(self, client):
        """Pitfall 5: malformed MAC → 422 (pydantic pattern, not 200/500)."""
        response = client.post("/api/bt/pair", json={"mac": "not-a-mac"})
        assert response.status_code == 422

    def test_pair_missing_mac_returns_422(self, client):
        """Missing MAC field → 422."""
        response = client.post("/api/bt/pair", json={"name": "JBL"})
        assert response.status_code == 422


class TestBtConnect:
    """POST /api/bt/connect (BT-04)."""

    def test_connect_returns_200_ok(self, client):
        """POST /api/bt/connect with valid MAC → 200 {ok:true}."""
        response = client.post("/api/bt/connect", json={"mac": "DD:EE:FF:33:44:55"})
        assert response.status_code == 200
        assert response.json() == {"ok": True}

    def test_connect_invalid_mac_returns_422(self, client):
        """Pitfall 5: short MAC → 422."""
        response = client.post("/api/bt/connect", json={"mac": "AA:BB"})
        assert response.status_code == 422


class TestBtDisconnect:
    """POST /api/bt/disconnect (BT-05)."""

    def test_disconnect_returns_200_ok(self, client):
        """POST /api/bt/disconnect (no body) → 200 {ok:true}."""
        response = client.post("/api/bt/disconnect")
        assert response.status_code == 200
        assert response.json() == {"ok": True}


class TestBtForget:
    """POST /api/bt/forget (BT-03)."""

    def test_forget_returns_200_ok(self, client):
        """POST /api/bt/forget with valid MAC → 200 {ok:true}."""
        response = client.post("/api/bt/forget", json={"mac": "AA:BB:CC:00:11:22"})
        assert response.status_code == 200
        assert response.json() == {"ok": True}

    def test_forget_invalid_mac_returns_422(self, client):
        """Pitfall 5: bad MAC → 422."""
        response = client.post("/api/bt/forget", json={"mac": "x"})
        assert response.status_code == 422


class TestBtStatusExtended:
    """Pitfall 7: GET /api/bt/status carries connected_mac + sink."""

    def test_status_has_connected_mac_key(self, client):
        response = client.get("/api/bt/status")
        data = response.json()
        assert "connected_mac" in data

    def test_status_has_sink_key(self, client):
        response = client.get("/api/bt/status")
        data = response.json()
        assert "sink" in data
        # Under fresh Mock, default sink is "wired".
        assert data["sink"] in {"wired", "bt"}
