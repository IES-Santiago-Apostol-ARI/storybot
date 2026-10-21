"""WiFi manager service — wraps nmcli subprocess calls for WiFi operations."""

import asyncio
import json
import re
import shutil
import sys


def _redact_args(args: list[str]) -> list[str]:
    """Return a copy of args with password/PSK values redacted."""
    out = list(args)
    for i, token in enumerate(out):
        if token in ("password", "wifi-sec.psk") and i + 1 < len(out):
            out[i + 1] = "***"
    return out


def _split_terse(line: str) -> list[str]:
    """Split one line of `nmcli -t` output into fields.

    nmcli escapes ':' and '\\' inside values with a backslash, so a plain
    split(":") breaks SSIDs or profile names that contain a colon.
    """
    fields: list[str] = []
    current: list[str] = []
    chars = iter(line)
    for ch in chars:
        if ch == "\\":
            current.append(next(chars, ""))
        elif ch == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(ch)
    fields.append("".join(current))
    return fields


def _key_mgmt_for(security: str | None) -> str | None:
    """Map an nmcli SECURITY column to a wifi-sec.key-mgmt value.

    None means an open network. Unknown networks default to WPA-PSK, which
    also covers WPA2/WPA3 transition-mode APs.
    """
    if security is None:
        return "wpa-psk"
    if security in ("", "--"):
        return None
    if "WPA3" in security and "WPA2" not in security and "WPA1" not in security:
        return "sae"
    return "wpa-psk"


async def _run_nmcli(*args: str, timeout_s: float = 20.0) -> tuple[str, str, int]:
    """Run nmcli command and return (stdout, stderr, returncode)."""
    proc = await asyncio.create_subprocess_exec(
        "nmcli",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        _log_event("nmcli_timeout", args=_redact_args(list(args)))
        return ("", "timeout", -1)
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
        Filters out hidden networks (blank SSIDs) per D-06. nmcli lists one
        row per access point (BSSID), so an SSID served by several APs or
        on both 2.4 and 5 GHz is merged into a single entry with the
        strongest signal.
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
        by_ssid: dict[str, dict] = {}
        for line in stdout.splitlines():
            parts = _split_terse(line)
            # Filter blank SSIDs (D-06)
            if len(parts) >= 4 and parts[0]:
                try:
                    signal = int(parts[1])
                except (ValueError, IndexError):
                    continue
                security = parts[2] if parts[2] not in ("", "--") else "open"
                connected = parts[3] == "*"
                existing = by_ssid.get(parts[0])
                if existing is None:
                    by_ssid[parts[0]] = {
                        "ssid": parts[0],
                        "signal": signal,
                        "security": security,
                        "connected": connected,
                    }
                    continue
                if signal > existing["signal"]:
                    existing["signal"] = signal
                    existing["security"] = security
                existing["connected"] = existing["connected"] or connected
        return sorted(by_ssid.values(), key=lambda n: n["signal"], reverse=True)

    async def _lookup_security(self, iface: str, ssid: str) -> str | None:
        """Return the SECURITY column for ssid from the cached scan, or None."""
        stdout, _, rc = await _run_nmcli(
            "-t",
            "-f",
            "SSID,SECURITY",
            "device",
            "wifi",
            "list",
            "ifname",
            iface,
            "--rescan",
            "no",
        )
        if rc != 0:
            return None
        for line in stdout.splitlines():
            parts = _split_terse(line)
            if len(parts) >= 2 and parts[0] == ssid:
                return parts[1]
        return None

    async def _delete_profiles_for(self, ssid: str) -> None:
        """Delete saved WiFi profiles named after ssid ("X", "X 1", "X 2"...).

        Earlier attempts (e.g. with a wrong password) leave profiles behind
        that nmcli would otherwise reuse with stale or incomplete secrets.
        """
        stdout, _, rc = await _run_nmcli(
            "-t", "-f", "UUID,NAME,TYPE", "connection", "show"
        )
        if rc != 0:
            return
        name_re = re.compile(re.escape(ssid) + r"( \d+)?")
        for line in stdout.splitlines():
            parts = _split_terse(line)
            if (
                len(parts) >= 3
                and parts[2] == "802-11-wireless"
                and name_re.fullmatch(parts[1])
            ):
                await _run_nmcli("connection", "delete", "uuid", parts[0])

    async def connect(self, ssid: str, password: str) -> bool:
        """Connect to a WiFi network.

        Builds an explicit NM connection profile (persists across reboots)
        instead of using `nmcli device wifi connect`, which on some NM
        versions fails with "key-mgmt: property is missing" or reuses a
        stale profile left by an earlier attempt. If activation fails the
        new profile is removed, so a wrong password is not retried forever.
        """
        iface = await self._detect_wifi_interface()
        key_mgmt = _key_mgmt_for(await self._lookup_security(iface, ssid))
        await self._delete_profiles_for(ssid)

        # PSK passed in argv for now. A future variant using 'nmcli --ask'
        # with the password piped via stdin avoids a brief exposure in 'ps'
        # output, but requires manual verification on the Jetson hardware.
        add_args = [
            "connection",
            "add",
            "type",
            "wifi",
            "ifname",
            iface,
            "con-name",
            ssid,
            "ssid",
            ssid,
            "connection.autoconnect",
            "yes",
        ]
        if key_mgmt is not None:
            add_args += ["wifi-sec.key-mgmt", key_mgmt, "wifi-sec.psk", password]
        _, stderr, rc = await _run_nmcli(*add_args)
        if rc != 0:
            _log_event("wifi_profile_add_failed", ssid=ssid, detail=stderr)
            return False

        # Association + DHCP can take well over 20s on busy/mesh networks.
        _, stderr, rc = await _run_nmcli(
            "--wait",
            "60",
            "connection",
            "up",
            "id",
            ssid,
            "ifname",
            iface,
            timeout_s=75.0,
        )
        if rc != 0:
            _log_event("wifi_connect_failed", ssid=ssid, detail=stderr)
            await _run_nmcli("connection", "delete", "id", ssid)
            return False
        return True

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
