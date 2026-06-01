"""Tests for wifi_manager — WiFi service with nmcli subprocess wrapping."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.models.wifi import WifiConnectRequest, WifiNetwork, WifiStatus
from app.services.wifi_manager import (
    MockWifiManager,
    RealWifiManager,
    WifiManager,
    create_wifi_manager,
)


# ---------------------------------------------------------------------------
# Subprocess mock helper (same pattern as test_swap_orchestrator.py)
# ---------------------------------------------------------------------------


def _make_subprocess_mock(returncode=0, stdout=b"", stderr=b""):
    proc = AsyncMock()
    proc.wait = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    return proc


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class TestWifiNetworkModel:
    """WifiNetwork model validation."""

    def test_valid_network(self):
        net = WifiNetwork(
            ssid="MyNetwork", signal=85, security="WPA2", connected=True
        )
        assert net.ssid == "MyNetwork"
        assert net.signal == 85
        assert net.security == "WPA2"
        assert net.connected is True

    def test_connected_defaults_false(self):
        net = WifiNetwork(ssid="OpenNet", signal=50, security="open")
        assert net.connected is False

    def test_signal_out_of_range_rejected(self):
        with pytest.raises(Exception):
            WifiNetwork(ssid="A", signal=150, security="WPA2")

    def test_negative_signal_rejected(self):
        with pytest.raises(Exception):
            WifiNetwork(ssid="A", signal=-1, security="WPA2")


class TestWifiConnectRequestModel:
    """WifiConnectRequest model validation."""

    def test_valid_request(self):
        req = WifiConnectRequest(ssid="Home", password="secret123")
        assert req.ssid == "Home"
        assert req.password == "secret123"

    def test_empty_ssid_rejected(self):
        with pytest.raises(Exception):
            WifiConnectRequest(ssid="", password="secret123")

    def test_short_password_rejected(self):
        with pytest.raises(Exception):
            WifiConnectRequest(ssid="Home", password="short")


class TestWifiStatusModel:
    """WifiStatus model validation."""

    def test_connected_status(self):
        st = WifiStatus(state="connected", ssid="Home", interface="wlan0")
        assert st.state == "connected"
        assert st.ssid == "Home"
        assert st.interface == "wlan0"

    def test_disconnected_status_ssid_optional(self):
        st = WifiStatus(state="disconnected", interface="wlan0")
        assert st.ssid is None


# ---------------------------------------------------------------------------
# Interface Detection (D-10)
# ---------------------------------------------------------------------------


class TestInterfaceDetection:
    """RealWifiManager._detect_wifi_interface auto-detects WiFi iface."""

    @patch("app.services.wifi_manager.asyncio.create_subprocess_exec")
    async def test_detects_wifi_interface(self, mock_exec):
        proc = _make_subprocess_mock(
            stdout=b"eth0:ethernet\nwlP1p1s0:wifi\n"
        )
        mock_exec.return_value = proc
        mgr = RealWifiManager()
        iface = await mgr._detect_wifi_interface()
        assert iface == "wlP1p1s0"

    @patch("app.services.wifi_manager.asyncio.create_subprocess_exec")
    async def test_detects_wlx_mac_format(self, mock_exec):
        proc = _make_subprocess_mock(
            stdout=b"wlx001122334455:wifi\neth0:ethernet\n"
        )
        mock_exec.return_value = proc
        mgr = RealWifiManager()
        iface = await mgr._detect_wifi_interface()
        assert iface == "wlx001122334455"

    @patch("app.services.wifi_manager.asyncio.create_subprocess_exec")
    async def test_no_wifi_interface_raises(self, mock_exec):
        proc = _make_subprocess_mock(stdout=b"eth0:ethernet\n")
        mock_exec.return_value = proc
        mgr = RealWifiManager()
        with pytest.raises(RuntimeError, match="No WiFi interface found"):
            await mgr._detect_wifi_interface()


# ---------------------------------------------------------------------------
# Scan (D-04, D-05, D-06)
# ---------------------------------------------------------------------------


class TestScan:
    """RealWifiManager.scan() parses nmcli terse output."""

    @patch("app.services.wifi_manager.asyncio.create_subprocess_exec")
    async def test_scan_parses_terse_output(self, mock_exec):
        # First call: device list for interface detection
        # Second call: rescan (non-fatal)
        # Third call: wifi list
        detect_proc = _make_subprocess_mock(
            stdout=b"wlP1p1s0:wifi\neth0:ethernet\n"
        )
        rescan_proc = _make_subprocess_mock(returncode=0)
        list_proc = _make_subprocess_mock(
            stdout=b"MyNetwork:85:WPA2:*\nOpenNet:42:--:\n"
        )
        mock_exec.side_effect = [detect_proc, rescan_proc, list_proc]
        mgr = RealWifiManager()
        result = await mgr.scan()
        assert len(result) == 2
        assert result[0]["ssid"] == "MyNetwork"
        assert result[0]["signal"] == 85
        assert result[0]["security"] == "WPA2"
        assert result[0]["connected"] is True
        assert result[1]["ssid"] == "OpenNet"
        assert result[1]["security"] == "open"
        assert result[1]["connected"] is False

    @patch("app.services.wifi_manager.asyncio.create_subprocess_exec")
    async def test_scan_filters_blank_ssids(self, mock_exec):
        """Hidden networks (blank SSIDs) are filtered out (D-06)."""
        detect_proc = _make_subprocess_mock(
            stdout=b"wlP1p1s0:wifi\n"
        )
        rescan_proc = _make_subprocess_mock(returncode=0)
        list_proc = _make_subprocess_mock(
            stdout=b":30:WPA2:\nMyNetwork:85:WPA2:*\n"
        )
        mock_exec.side_effect = [detect_proc, rescan_proc, list_proc]
        mgr = RealWifiManager()
        result = await mgr.scan()
        assert len(result) == 1
        assert result[0]["ssid"] == "MyNetwork"

    @patch("app.services.wifi_manager.asyncio.create_subprocess_exec")
    async def test_rescan_failure_is_nonfatal(self, mock_exec):
        """Rescan failure logs warning, still returns list results."""
        detect_proc = _make_subprocess_mock(
            stdout=b"wlP1p1s0:wifi\n"
        )
        rescan_proc = _make_subprocess_mock(
            returncode=1, stderr=b"Error: not authorized"
        )
        list_proc = _make_subprocess_mock(
            stdout=b"MyNetwork:85:WPA2:*\n"
        )
        mock_exec.side_effect = [detect_proc, rescan_proc, list_proc]
        mgr = RealWifiManager()
        result = await mgr.scan()
        assert len(result) == 1

    @patch("app.services.wifi_manager.asyncio.create_subprocess_exec")
    async def test_scan_includes_signal_security_connected_fields(self, mock_exec):
        """D-05: scan returns ssid, signal, security, connected fields."""
        detect_proc = _make_subprocess_mock(
            stdout=b"wlP1p1s0:wifi\n"
        )
        rescan_proc = _make_subprocess_mock(returncode=0)
        list_proc = _make_subprocess_mock(
            stdout=b"TestNet:75:WPA3:*\n"
        )
        mock_exec.side_effect = [detect_proc, rescan_proc, list_proc]
        mgr = RealWifiManager()
        result = await mgr.scan()
        assert len(result) == 1
        net = result[0]
        assert "ssid" in net
        assert "signal" in net
        assert "security" in net
        assert "connected" in net


# ---------------------------------------------------------------------------
# Connect (D-01, WIFI-04)
# ---------------------------------------------------------------------------


class TestConnect:
    """RealWifiManager.connect(ssid, password) wraps nmcli connect."""

    @patch("app.services.wifi_manager.asyncio.create_subprocess_exec")
    async def test_connect_returns_true_on_success(self, mock_exec):
        detect_proc = _make_subprocess_mock(
            stdout=b"wlP1p1s0:wifi\n"
        )
        connect_proc = _make_subprocess_mock(
            returncode=0,
            stdout=b"Device 'wlP1p1s0' successfully activated with 'abc'.\n",
        )
        mock_exec.side_effect = [detect_proc, connect_proc]
        mgr = RealWifiManager()
        result = await mgr.connect("MyNetwork", "secret123")
        assert result is True

    @patch("app.services.wifi_manager.asyncio.create_subprocess_exec")
    async def test_connect_returns_false_on_failure(self, mock_exec):
        detect_proc = _make_subprocess_mock(
            stdout=b"wlP1p1s0:wifi\n"
        )
        connect_proc = _make_subprocess_mock(
            returncode=1,
            stderr=b"Error: Connection activation failed.\n",
        )
        mock_exec.side_effect = [detect_proc, connect_proc]
        mgr = RealWifiManager()
        result = await mgr.connect("BadNetwork", "secret123")
        assert result is False

    @patch("app.services.wifi_manager.asyncio.create_subprocess_exec")
    async def test_connect_calls_nmcli_with_correct_args(self, mock_exec):
        """Verify connect uses correct nmcli command with ssid and password."""
        detect_proc = _make_subprocess_mock(
            stdout=b"wlP1p1s0:wifi\n"
        )
        connect_proc = _make_subprocess_mock(returncode=0)
        mock_exec.side_effect = [detect_proc, connect_proc]
        mgr = RealWifiManager()
        await mgr.connect("TestSSID", "testpass123")
        # Second call is the connect command
        connect_call = mock_exec.call_args_list[1]
        assert "nmcli" in connect_call[0]
        assert "device" in connect_call[0]
        assert "wifi" in connect_call[0]
        assert "connect" in connect_call[0]
        assert "TestSSID" in connect_call[0]
        assert "password" in connect_call[0]
        assert "testpass123" in connect_call[0]
        assert "ifname" in connect_call[0]


# ---------------------------------------------------------------------------
# Disconnect (D-03, WIFI-05)
# ---------------------------------------------------------------------------


class TestDisconnect:
    """RealWifiManager.disconnect() uses 'connection down' (D-03)."""

    @patch("app.services.wifi_manager.asyncio.create_subprocess_exec")
    async def test_disconnect_uses_connection_down(self, mock_exec):
        """Verify disconnect uses 'connection down', not 'device disconnect'."""
        active_proc = _make_subprocess_mock(
            stdout=b"MyNetwork:802-11-wireless:wlP1p1s0\n"
        )
        down_proc = _make_subprocess_mock(returncode=0)
        mock_exec.side_effect = [active_proc, down_proc]
        mgr = RealWifiManager()
        result = await mgr.disconnect()
        assert result is True
        # Second call should be 'connection down'
        down_call = mock_exec.call_args_list[1]
        assert "connection" in down_call[0]
        assert "down" in down_call[0]
        assert "MyNetwork" in down_call[0]

    @patch("app.services.wifi_manager.asyncio.create_subprocess_exec")
    async def test_disconnect_returns_false_no_active_wifi(self, mock_exec):
        """No active WiFi connection -> returns False."""
        active_proc = _make_subprocess_mock(
            stdout=b"eth0:802-3-ethernet:eth0\n"
        )
        mock_exec.return_value = active_proc
        mgr = RealWifiManager()
        result = await mgr.disconnect()
        assert result is False

    @patch("app.services.wifi_manager.asyncio.create_subprocess_exec")
    async def test_disconnect_returns_false_on_failure(self, mock_exec):
        active_proc = _make_subprocess_mock(
            stdout=b"MyNetwork:802-11-wireless:wlP1p1s0\n"
        )
        down_proc = _make_subprocess_mock(returncode=1)
        mock_exec.side_effect = [active_proc, down_proc]
        mgr = RealWifiManager()
        result = await mgr.disconnect()
        assert result is False


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


class TestStatus:
    """RealWifiManager.status() returns state, ssid, interface."""

    @patch("app.services.wifi_manager.asyncio.create_subprocess_exec")
    async def test_status_connected(self, mock_exec):
        detect_proc = _make_subprocess_mock(
            stdout=b"wlP1p1s0:wifi\n"
        )
        show_proc = _make_subprocess_mock(
            stdout=b"GENERAL.STATE:100 (connected)\nGENERAL.CONNECTION:MyNetwork\n"
        )
        mock_exec.side_effect = [detect_proc, show_proc]
        mgr = RealWifiManager()
        result = await mgr.status()
        assert result["state"] == "connected"
        assert result["ssid"] == "MyNetwork"
        assert result["interface"] == "wlP1p1s0"

    @patch("app.services.wifi_manager.asyncio.create_subprocess_exec")
    async def test_status_disconnected(self, mock_exec):
        detect_proc = _make_subprocess_mock(
            stdout=b"wlP1p1s0:wifi\n"
        )
        show_proc = _make_subprocess_mock(
            stdout=b"GENERAL.STATE:30 (disconnected)\nGENERAL.CONNECTION:--\n"
        )
        mock_exec.side_effect = [detect_proc, show_proc]
        mgr = RealWifiManager()
        result = await mgr.status()
        assert result["state"] == "disconnected"
        assert result["ssid"] is None
        assert result["interface"] == "wlP1p1s0"


# ---------------------------------------------------------------------------
# MockWifiManager (D-08)
# ---------------------------------------------------------------------------


class TestMockWifiManager:
    """MockWifiManager returns fake data for testing."""

    def test_is_mock_true(self):
        mgr = MockWifiManager()
        assert mgr.is_mock is True

    async def test_scan_returns_two_networks(self):
        mgr = MockWifiManager()
        result = await mgr.scan()
        assert len(result) == 2
        assert all("ssid" in n for n in result)

    async def test_connect_always_succeeds(self):
        mgr = MockWifiManager()
        result = await mgr.connect("AnyNetwork", "anypassword")
        assert result is True

    async def test_disconnect_always_succeeds(self):
        mgr = MockWifiManager()
        result = await mgr.disconnect()
        assert result is True

    async def test_status_returns_disconnected(self):
        mgr = MockWifiManager()
        result = await mgr.status()
        assert result["state"] == "disconnected"
        assert result["ssid"] is None
        assert result["interface"] == "mock0"


# ---------------------------------------------------------------------------
# Factory (D-08, D-09)
# ---------------------------------------------------------------------------


class TestFactory:
    """create_wifi_manager() returns Real or Mock based on nmcli availability."""

    @patch("app.services.wifi_manager.shutil.which", return_value="/usr/bin/nmcli")
    def test_factory_returns_real_when_nmcli_available(self, mock_which):
        mgr = create_wifi_manager()
        assert isinstance(mgr, RealWifiManager)
        assert mgr.is_mock is False

    @patch("app.services.wifi_manager.shutil.which", return_value=None)
    def test_factory_returns_mock_when_nmcli_missing(self, mock_which):
        mgr = create_wifi_manager()
        assert isinstance(mgr, MockWifiManager)
        assert mgr.is_mock is True

    @patch("app.services.wifi_manager.shutil.which", return_value=None)
    def test_factory_creates_new_instance_each_call(self, mock_which):
        """D-09: factory is called per-request, no singleton."""
        mgr1 = create_wifi_manager()
        mgr2 = create_wifi_manager()
        assert mgr1 is not mgr2


# ---------------------------------------------------------------------------
# Base class contract
# ---------------------------------------------------------------------------


class TestWifiManagerBaseClass:
    """WifiManager base class defines interface and raises NotImplementedError."""

    def test_base_class_is_mock_false(self):
        mgr = WifiManager()
        assert mgr.is_mock is False

    async def test_base_scan_raises(self):
        mgr = WifiManager()
        with pytest.raises(NotImplementedError):
            await mgr.scan()

    async def test_base_connect_raises(self):
        mgr = WifiManager()
        with pytest.raises(NotImplementedError):
            await mgr.connect("ssid", "password")

    async def test_base_disconnect_raises(self):
        mgr = WifiManager()
        with pytest.raises(NotImplementedError):
            await mgr.disconnect()

    async def test_base_status_raises(self):
        mgr = WifiManager()
        with pytest.raises(NotImplementedError):
            await mgr.status()
