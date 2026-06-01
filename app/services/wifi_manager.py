"""WiFi manager service — wraps nmcli subprocess calls for WiFi operations."""

import asyncio
import json
import shutil
import sys


async def _run_nmcli(*args: str) -> tuple[str, str, int]:
    """Run nmcli command and return (stdout, stderr, returncode)."""
    proc = await asyncio.create_subprocess_exec(
        "nmcli",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return (
        stdout.decode().strip(),
        stderr.decode().strip(),
        proc.returncode if proc.returncode is not None else -1,
    )


def _log_event(event: str, **kwargs: object) -> None:
    """Structured JSON log to stderr (same pattern as swap_orchestrator)."""
    print(
        json.dumps({"event": event, **kwargs}),
        file=sys.stderr,
    )


class WifiManager:
    """Base contract for WiFi management operations."""

    is_mock: bool = False

    async def scan(self) -> list[dict]:
        raise NotImplementedError

    async def connect(self, ssid: str, password: str) -> bool:
        raise NotImplementedError

    async def disconnect(self) -> bool:
        raise NotImplementedError

    async def status(self) -> dict:
        raise NotImplementedError


class RealWifiManager(WifiManager):
    """Real WiFi manager wrapping nmcli subprocess calls."""

    is_mock: bool = False

    async def _detect_wifi_interface(self) -> str:
        """Detect the WiFi interface name at runtime.

        Returns the first wifi-type device from NetworkManager.
        Handles predictable naming (wlP1p1s0, wlx<mac>, wlan0).
        """
        stdout, _, rc = await _run_nmcli("-t", "-f", "DEVICE,TYPE", "device")
        if rc != 0:
            raise RuntimeError("Failed to list network devices")
        for line in stdout.splitlines():
            parts = line.split(":")
            if len(parts) == 2 and parts[1] == "wifi":
                return parts[0]
        raise RuntimeError("No WiFi interface found")

    async def scan(self) -> list[dict]:
        """Scan for WiFi networks.

        Lists networks forcing a fresh blocking scan (--rescan yes); falls
        back to cached results if that scan is denied or rate-limited.
        Filters out hidden networks (blank SSIDs) per D-06.
        """
        iface = await self._detect_wifi_interface()
        # List networks, forcing a fresh blocking scan. `--rescan yes` makes
        # nmcli perform a new scan and wait for the results, instead of
        # returning the stale cache — which often holds only the currently
        # connected AP and was the cause of "Actualizar" showing one network.
        stdout, rescan_stderr, rc = await _run_nmcli(
            "-t",
            "-f",
            "SSID,SIGNAL,SECURITY,IN-USE",
            "device",
            "wifi",
            "list",
            "ifname",
            iface,
            "--rescan",
            "yes",
        )
        if rc != 0:
            # A fresh scan may be denied (no polkit auth) or rate-limited.
            # Fall back to cached results so scan still returns something.
            _log_event(
                "wifi_rescan_failed",
                interface=iface,
                detail=rescan_stderr,
            )
            stdout, _, _ = await _run_nmcli(
                "-t",
                "-f",
                "SSID,SIGNAL,SECURITY,IN-USE",
                "device",
                "wifi",
                "list",
                "ifname",
                iface,
                "--rescan",
                "no",
            )
        networks: list[dict] = []
        for line in stdout.splitlines():
            parts = line.split(":", 3)
            # Filter blank SSIDs (D-06)
            if len(parts) >= 4 and parts[0]:
                try:
                    signal = int(parts[1])
                except (ValueError, IndexError):
                    continue
                security = parts[2] if parts[2] != "--" else "open"
                networks.append(
                    {
                        "ssid": parts[0],
                        "signal": signal,
                        "security": security,
                        "connected": parts[3] == "*",
                    }
                )
        return networks

    async def connect(self, ssid: str, password: str) -> bool:
        """Connect to a WiFi network.

        Creates/updates a NM connection profile that persists across reboots.
        """
        iface = await self._detect_wifi_interface()
        stdout, stderr, rc = await _run_nmcli(
            "device",
            "wifi",
            "connect",
            ssid,
            "password",
            password,
            "ifname",
            iface,
        )
        return rc == 0

    async def disconnect(self) -> bool:
        """Disconnect from current WiFi without deleting the profile.

        Uses 'connection down' (not 'device disconnect') to allow
        auto-reconnect on next boot (WIFI-04 / D-03).
        """
        stdout, _, rc = await _run_nmcli(
            "-t",
            "-f",
            "NAME,TYPE,DEVICE",
            "connection",
            "show",
            "--active",
        )
        for line in stdout.splitlines():
            parts = line.split(":", 2)
            if len(parts) >= 3 and parts[1] == "802-11-wireless":
                conn_name = parts[0]
                _, _, down_rc = await _run_nmcli("connection", "down", conn_name)
                return down_rc == 0
        return False  # No active WiFi connection

    async def status(self) -> dict:
        """Get current WiFi connection status."""
        iface = await self._detect_wifi_interface()
        stdout, _, rc = await _run_nmcli(
            "-t",
            "-f",
            "GENERAL.STATE,GENERAL.CONNECTION",
            "device",
            "show",
            iface,
        )
        state = "disconnected"
        connection = None
        for line in stdout.splitlines():
            if line.startswith("GENERAL.STATE:"):
                val = line.split(":", 1)[1]
                # NM states >= 100 are connected variants:
                # 100 (connected), 110 (local), 120 (site), 130 (global)
                try:
                    code = int(val.split()[0])
                    if code >= 100:
                        state = "connected"
                except (ValueError, IndexError):
                    pass
            elif line.startswith("GENERAL.CONNECTION:"):
                val = line.split(":", 1)[1]
                if val and val != "--":
                    connection = val
        return {"state": state, "ssid": connection, "interface": iface}


class MockWifiManager(WifiManager):
    """Mock WiFi manager for testing without WiFi hardware."""

    is_mock: bool = True

    async def scan(self) -> list[dict]:
        return [
            {
                "ssid": "MockNetwork1",
                "signal": 85,
                "security": "WPA2",
                "connected": False,
            },
            {
                "ssid": "MockNetwork2",
                "signal": 60,
                "security": "open",
                "connected": False,
            },
        ]

    async def connect(self, ssid: str, password: str) -> bool:
        return True

    async def disconnect(self) -> bool:
        return True

    async def status(self) -> dict:
        return {"state": "disconnected", "ssid": None, "interface": "mock0"}


def create_wifi_manager() -> WifiManager:
    """Create appropriate WiFi manager based on nmcli availability.

    Returns:
        RealWifiManager if nmcli is available, else MockWifiManager.
    """
    if shutil.which("nmcli"):
        return RealWifiManager()
    return MockWifiManager()
