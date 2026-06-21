"""Tests for WiFi API endpoints — scan, connect, disconnect, status."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(monkeypatch):
    """Create test client with lifespan context.

    Force AI enabled so the app boots fully.
    """
    monkeypatch.setenv("STORYBOT_AI", "1")
    with TestClient(app) as c:
        yield c


def _mock_wifi_manager(
    scan_return=None,
    connect_return=True,
    disconnect_return=True,
    status_return=None,
    connect_side_effect=None,
):
    """Create a mock WifiManager with configurable behavior."""
    mgr = AsyncMock()
    mgr.is_mock = True
    mgr.scan = AsyncMock(
        return_value=scan_return
        if scan_return is not None
        else [
            {
                "ssid": "TestNet",
                "signal": 75,
                "security": "WPA2",
                "connected": False,
            }
        ]
    )
    mgr.connect = AsyncMock(return_value=connect_return)
    if connect_side_effect:
        mgr.connect = AsyncMock(side_effect=connect_side_effect)
    mgr.disconnect = AsyncMock(return_value=disconnect_return)
    mgr.status = AsyncMock(
        return_value=status_return
        if status_return is not None
        else {"state": "disconnected", "ssid": None, "interface": "wlan0"}
    )
    return mgr


@patch("app.routers.wifi.create_wifi_manager")
class TestWifiScan:
    """Test GET /api/wifi/scan endpoint."""

    def test_scan_returns_200(self, mock_factory, client):
        """GET /api/wifi/scan returns 200 status."""
        mock_factory.return_value = _mock_wifi_manager()
        response = client.get("/api/wifi/scan")
        assert response.status_code == 200

    def test_scan_returns_list_of_networks(self, mock_factory, client):
        """GET /api/wifi/scan returns list with correct shape."""
        networks = [
            {"ssid": "HomeNet", "signal": 85, "security": "WPA2", "connected": True},
            {"ssid": "GuestNet", "signal": 40, "security": "open", "connected": False},
        ]
        mock_factory.return_value = _mock_wifi_manager(scan_return=networks)
        response = client.get("/api/wifi/scan")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["ssid"] == "HomeNet"
        assert data[0]["signal"] == 85
        assert data[0]["security"] == "WPA2"
        assert data[0]["connected"] is True

    def test_scan_each_network_has_required_fields(self, mock_factory, client):
        """Each network object has ssid, signal, security, connected."""
        mock_factory.return_value = _mock_wifi_manager(
            scan_return=[
                {"ssid": "Net", "signal": 50, "security": "WPA3", "connected": False}
            ]
        )
        response = client.get("/api/wifi/scan")
        data = response.json()
        net = data[0]
        assert "ssid" in net
        assert "signal" in net
        assert "security" in net
        assert "connected" in net


@patch("app.routers.wifi.create_wifi_manager")
class TestWifiConnect:
    """Test POST /api/wifi/connect endpoint."""

    def test_connect_success_returns_ok_true(self, mock_factory, client):
        """Successful connect returns {"ok": true}."""
        mock_factory.return_value = _mock_wifi_manager(connect_return=True)
        response = client.post(
            "/api/wifi/connect",
            json={"ssid": "HomeNet", "password": "securepass123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_connect_failure_returns_ok_false(self, mock_factory, client):
        """Failed connect returns {"ok": false, "error": "connection_failed"}."""
        mock_factory.return_value = _mock_wifi_manager(connect_return=False)
        response = client.post(
            "/api/wifi/connect",
            json={"ssid": "BadNet", "password": "wrongpass123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert data["error"] == "connection_failed"

    def test_connect_exception_returns_error_with_type(self, mock_factory, client):
        """Exception during connect returns {"ok": false, "error": "<ExceptionType>"}."""
        mock_factory.return_value = _mock_wifi_manager(
            connect_side_effect=RuntimeError("timeout")
        )
        response = client.post(
            "/api/wifi/connect",
            json={"ssid": "CrashNet", "password": "somepassword"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert data["error"] == "RuntimeError"

    def test_connect_missing_ssid_returns_422(self, mock_factory, client):
        """Missing ssid field returns 422 validation error."""
        mock_factory.return_value = _mock_wifi_manager()
        response = client.post(
            "/api/wifi/connect",
            json={"password": "somepassword"},
        )
        assert response.status_code == 422

    def test_connect_missing_password_returns_422(self, mock_factory, client):
        """Missing password field returns 422 validation error."""
        mock_factory.return_value = _mock_wifi_manager()
        response = client.post(
            "/api/wifi/connect",
            json={"ssid": "SomeNet"},
        )
        assert response.status_code == 422

    def test_connect_short_password_returns_422(self, mock_factory, client):
        """Password shorter than 8 chars returns 422 validation error."""
        mock_factory.return_value = _mock_wifi_manager()
        response = client.post(
            "/api/wifi/connect",
            json={"ssid": "SomeNet", "password": "short"},
        )
        assert response.status_code == 422

    def test_connect_empty_ssid_returns_422(self, mock_factory, client):
        """Empty ssid returns 422 validation error."""
        mock_factory.return_value = _mock_wifi_manager()
        response = client.post(
            "/api/wifi/connect",
            json={"ssid": "", "password": "somepassword"},
        )
        assert response.status_code == 422

    def test_connect_passes_ssid_and_password_to_manager(self, mock_factory, client):
        """Router passes body.ssid and body.password to manager.connect()."""
        mgr = _mock_wifi_manager(connect_return=True)
        mock_factory.return_value = mgr
        client.post(
            "/api/wifi/connect",
            json={"ssid": "MyNetwork", "password": "MyPassword1"},
        )
        mgr.connect.assert_awaited_once_with("MyNetwork", "MyPassword1")


@patch("app.routers.wifi.create_wifi_manager")
class TestWifiDisconnect:
    """Test POST /api/wifi/disconnect endpoint."""

    def test_disconnect_success_returns_ok_true(self, mock_factory, client):
        """Successful disconnect returns {"ok": true}."""
        mock_factory.return_value = _mock_wifi_manager(disconnect_return=True)
        response = client.post("/api/wifi/disconnect")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_disconnect_failure_returns_ok_false(self, mock_factory, client):
        """Failed disconnect (no active connection) returns {"ok": false, "error": "not_connected"}."""
        mock_factory.return_value = _mock_wifi_manager(disconnect_return=False)
        response = client.post("/api/wifi/disconnect")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert data["error"] == "not_connected"


@patch("app.routers.wifi.create_wifi_manager")
class TestWifiStatus:
    """Test GET /api/wifi/status endpoint."""

    def test_status_returns_200(self, mock_factory, client):
        """GET /api/wifi/status returns 200 status."""
        mock_factory.return_value = _mock_wifi_manager()
        response = client.get("/api/wifi/status")
        assert response.status_code == 200

    def test_status_returns_correct_shape(self, mock_factory, client):
        """Status response has state, ssid, interface fields."""
        mock_factory.return_value = _mock_wifi_manager(
            status_return={"state": "connected", "ssid": "HomeNet", "interface": "wlan0"}
        )
        response = client.get("/api/wifi/status")
        assert response.status_code == 200
        data = response.json()
        assert data["state"] == "connected"
        assert data["ssid"] == "HomeNet"
        assert data["interface"] == "wlan0"

    def test_status_disconnected_returns_null_ssid(self, mock_factory, client):
        """Disconnected status has ssid as null."""
        mock_factory.return_value = _mock_wifi_manager(
            status_return={"state": "disconnected", "ssid": None, "interface": "wlxabc"}
        )
        response = client.get("/api/wifi/status")
        data = response.json()
        assert data["state"] == "disconnected"
        assert data["ssid"] is None
        assert data["interface"] == "wlxabc"


@patch("app.routers.wifi.create_wifi_manager")
class TestWifiRouterRegistration:
    """Test that WiFi router is registered and accessible.

    The factory is mocked so these registration checks never reach the real
    RealWifiManager: on a host where nmcli exists, an unmocked POST to
    /api/wifi/disconnect runs `nmcli connection down <conn>` and drops the
    machine's actual WiFi.
    """

    def test_wifi_scan_endpoint_exists(self, mock_factory, client):
        """GET /api/wifi/scan is registered (not 404)."""
        mock_factory.return_value = _mock_wifi_manager()
        response = client.get("/api/wifi/scan")
        assert response.status_code != 404

    def test_wifi_connect_endpoint_exists(self, mock_factory, client):
        """POST /api/wifi/connect is registered (not 404)."""
        mock_factory.return_value = _mock_wifi_manager()
        response = client.post(
            "/api/wifi/connect",
            json={"ssid": "test", "password": "testpass12"},
        )
        assert response.status_code != 404

    def test_wifi_disconnect_endpoint_exists(self, mock_factory, client):
        """POST /api/wifi/disconnect is registered (not 404)."""
        mock_factory.return_value = _mock_wifi_manager()
        response = client.post("/api/wifi/disconnect")
        assert response.status_code != 404

    def test_wifi_status_endpoint_exists(self, mock_factory, client):
        """GET /api/wifi/status is registered (not 404)."""
        mock_factory.return_value = _mock_wifi_manager()
        response = client.get("/api/wifi/status")
        assert response.status_code != 404
