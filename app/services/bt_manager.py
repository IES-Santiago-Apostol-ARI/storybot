"""Bluetooth manager service — BlueZ discovery over D-Bus via dbus-fast.

Structural clone of app/services/wifi_manager.py (base contract → Real → Mock →
never-raises factory) + app/services/printer_handler.py (lazy hardware import +
TESTING fallback). The only genuinely new surface is the dbus-fast BlueZ call
sequence, isolated behind a single patchable seam (_get_managed_objects) so the
tests stay robust against the deep async object graph (RESEARCH Pitfall 6).
"""

import asyncio
import glob
import json
import os
import sys
from datetime import datetime, timezone

from app.services import bt_audio
from app.services.bt_agent import register_agent
from app.services.bt_store import BtDeviceStore

# Lazy hardware import — module stays importable where dbus-fast is absent
# (CI / Mock-only machines). Pattern copied from printer_handler.py lines 14-26.
try:
    from dbus_fast.aio import MessageBus  # type: ignore
    from dbus_fast.constants import BusType  # type: ignore

    _DBUS_FAST_AVAILABLE = True
except Exception:  # pragma: no cover — exercised on machines without dbus-fast
    MessageBus = None  # type: ignore
    BusType = None  # type: ignore
    _DBUS_FAST_AVAILABLE = False


# Fixed blocking discovery window in seconds (D-04: ~8-10s range; no SSE).
SCAN_WINDOW_S = 8.0


# A2DP Audio Sink service UUID (Bluetooth SIG assigned number 0x110B).
# Match if a device advertises this — it identifies an A2DP-capable speaker.
# Related: A2DP Source = 0000110a (NOT a sink — must not match alone).
A2DP_SINK_UUID = "0000110b-0000-1000-8000-00805f9b34fb"


def _log_event(event: str, **kwargs: object) -> None:
    """Structured JSON log to stderr (same pattern as wifi_manager)."""
    print(
        json.dumps({"event": event, **kwargs}),
        file=sys.stderr,
    )


def _is_audio(props: dict) -> bool:
    """D-05: return True if the BlueZ Device1 props indicate an audio device.

    Matches if ANY of:
      1. Class-of-Device major class == Audio/Video (bits 8-12 == 0x04).
      2. A2DP sink service UUID present in ``UUIDs`` (case-insensitive).
      3. ``Icon == "audio-card"`` (weak fallback).

    Args:
        props: Device1 property dict with values already unwrapped from
            dbus-fast Variants (callers pass the unwrapped dict). Both
            ``None`` values and missing keys are treated as "absent".
    """
    cod = props.get("Class")
    if cod is not None and ((cod >> 8) & 0x1F) == 0x04:
        return True
    uuids = props.get("UUIDs") or []
    if any(str(u).lower() == A2DP_SINK_UUID for u in uuids):
        return True
    return props.get("Icon") == "audio-card"


def _unwrap(value):
    """Return ``value.value`` for a dbus-fast Variant, else ``value`` itself.

    GetManagedObjects wraps every property in a Variant; we strip the wrapper
    so downstream code (sorting, JSON serialization, pydantic) sees plain
    Python types (Pitfall 2 / T-26-07).
    """
    return getattr(value, "value", value)


def _to_entries(managed: dict) -> list[dict]:
    """Filter GetManagedObjects output to audio-only, RSSI-sorted entries.

    Args:
        managed: BlueZ ``{path: {iface: {prop: Variant}}}`` shape as returned
            by ``org.freedesktop.DBus.ObjectManager.GetManagedObjects()``.

    Returns:
        List of ``{"name": str, "mac": str, "rssi": int | None}`` dicts
        (BT-01). Audio-only (D-05), strongest RSSI first with missing RSSI
        last (D-06). Every prop value is unwrapped from its dbus Variant so
        callers never see ``signature``/``value`` keys leak into JSON.
    """
    out: list[dict] = []
    for path, ifaces in managed.items():
        dev = ifaces.get("org.bluez.Device1")
        if not dev:
            continue  # adapter objects / Battery1 / other interfaces skipped
        # Unwrap Variant values once, then run pure logic on plain types.
        props = {k: _unwrap(v) for k, v in dev.items()}
        if not _is_audio(props):
            continue
        out.append(
            {
                "name": props.get("Alias") or props.get("Name") or props.get("Address"),
                "mac": props.get("Address"),
                "rssi": props.get(
                    "RSSI"
                ),  # may be missing for cached devices (Pitfall 3)
            }
        )
    # D-06: strongest RSSI first (highest dBm, i.e. least-negative); missing
    # RSSI sorts last. ``-(d["rssi"] or 0)`` ranks present values descending;
    # the leading ``is None`` flag pushes missing values to the back.
    out.sort(key=lambda d: (d["rssi"] is None, -(d["rssi"] or 0)))
    return out


def _bt_adapter_present() -> bool:
    """Return True if a Bluetooth adapter (hci*) is present on this host.

    Synchronous filesystem probe — the BT analog of wifi_manager's
    ``shutil.which("nmcli")`` gate. Used by the factory to route a machine
    with dbus but no BT radio straight to MockBtManager (RESEARCH Open
    Question 2). Never raises: glob errors resolve to False.
    """
    try:
        return bool(glob.glob("/sys/class/bluetooth/hci*"))
    except OSError:  # pragma: no cover — defensive; glob is very tolerant
        return False


# ---------------------------------------------------------------------------
# Service family: base contract → Real (dbus-fast) → Mock → never-raises
# factory. Structural clone of wifi_manager.py + printer_handler.py (PLAT-03).
# ---------------------------------------------------------------------------


# Default BlueZ adapter path. RESEARCH Pattern 1 / Domain Reference: hci0 is
# the conventional first adapter; if absent, GetManagedObjects-based adapter
# discovery is the fallback path (documented, not needed for the happy path).
_ADAPTER_PATH = "/org/bluez/hci0"
_BLUEZ_SERVICE = "org.bluez"


class BtManager:
    """Base contract for Bluetooth management operations (PLAT-03).

    Mirrors WifiManager's base class shape. Satisfies the HardwareService
    Protocol (``is_mock`` + ``async get_status()``). Every method raises
    NotImplementedError in the base — concrete behavior lives in Real/Mock.
    """

    is_mock: bool = False

    async def scan(self) -> list[dict]:
        raise NotImplementedError

    async def get_last_speaker(self) -> dict | None:
        raise NotImplementedError

    async def remember_speaker(self, name: str, mac: str) -> None:
        raise NotImplementedError

    async def pair(self, mac: str, name: str | None = None) -> dict:
        raise NotImplementedError

    async def connect(self, mac: str) -> dict:
        raise NotImplementedError

    async def disconnect(self, mac: str | None = None) -> dict:
        raise NotImplementedError

    async def forget(self, mac: str) -> dict:
        raise NotImplementedError

    async def get_status(self) -> dict:
        raise NotImplementedError


class RealBtManager(BtManager):
    """Real Bluetooth manager — BlueZ discovery over D-Bus via dbus-fast.

    The full dbus chain (bus connect → introspect → Adapter1.StartDiscovery →
    sleep → StopDiscovery → ObjectManager.GetManagedObjects → disconnect) is
    isolated inside ``_get_managed_objects()`` so tests can patch ONE seam
    instead of the deep async object graph (RESEARCH Pitfall 6). ``scan()``
    wraps that seam in try/except so absent hardware / BlueZ-down returns
    ``[]`` and logs ``bt_scan_unavailable`` rather than raising (Pitfall 4,
    threat T-26-05).

    Memory (BT-06) delegates to a ``BtDeviceStore`` — injectable via the
    ``store`` kwarg so tests can target a tmp_path.
    """

    is_mock: bool = False

    def __init__(self, store: BtDeviceStore | None = None) -> None:
        # BtDeviceStore is cheap to construct and never raises on a missing
        # file (load-with-defaults). Default path = content/bt_devices.json.
        self._store = store if store is not None else BtDeviceStore()
        # Connection state for get_status (Pitfall 7). Updated on a successful
        # connect/pair (sink="bt") and reset on disconnect/forget (sink="wired").
        self._connected_mac: str | None = None
        self._current_sink = "wired"

    async def _get_managed_objects(self) -> dict:
        """Run the blocking ~8-10s BlueZ discovery window, return managed objs.

        Per-call short-lived SYSTEM bus connection (RESEARCH Pattern 1):
        connect → introspect adapter → ensure Powered + StartDiscovery →
        sleep SCAN_WINDOW_S (D-04, no SSE) → StopDiscovery → GetManagedObjects
        on ``/`` → disconnect. Returns the raw
        ``{path: {iface: {prop: Variant}}}`` dict for ``_to_entries``.

        Raises on any dbus failure (no adapter, service down, permission
        denied); ``scan()`` catches and degrades to ``[]``.
        """
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        try:
            intro = await bus.introspect(_BLUEZ_SERVICE, _ADAPTER_PATH)
            adapter_obj = bus.get_proxy_object(_BLUEZ_SERVICE, _ADAPTER_PATH, intro)
            adapter = adapter_obj.get_interface("org.bluez.Adapter1")
            # Pitfall 5: ensure the radio is Powered before discovery.
            props_iface = adapter_obj.get_interface("org.freedesktop.DBus.Properties")
            try:
                powered = await props_iface.call_get("org.bluez.Adapter1", "Powered")
                if not powered.value:
                    await props_iface.call_set(
                        "org.bluez.Adapter1", "Powered", _variant_wrap(True)
                    )
            except Exception:  # pragma: no cover — best-effort power-on
                pass
            await adapter.call_start_discovery()
            try:
                # D-04: blocking window — discover for a fixed ~8-10s, then
                # return a single list (no SSE streaming this phase).
                await asyncio.sleep(SCAN_WINDOW_S)
            finally:
                await adapter.call_stop_discovery()

            root_intro = await bus.introspect(_BLUEZ_SERVICE, "/")
            root = bus.get_proxy_object(_BLUEZ_SERVICE, "/", root_intro)
            om = root.get_interface("org.freedesktop.DBus.ObjectManager")
            return await om.call_get_managed_objects()
        finally:
            bus.disconnect()

    async def scan(self) -> list[dict]:
        """Discover nearby audio devices (D-04/D-05/D-06, BT-01/BT-07).

        Wraps ``_get_managed_objects()`` in try/except: absent adapter /
        BlueZ-down / dbus failure → ``[]`` + ``bt_scan_unavailable`` log
        (Pitfall 4, threat T-26-05). Never raises.
        """
        try:
            managed = await self._get_managed_objects()
        except Exception as exc:
            _log_event("bt_scan_unavailable", reason=type(exc).__name__)
            return []
        return _to_entries(managed)

    async def get_last_speaker(self) -> dict | None:
        """BT-06: delegate to BtDeviceStore (never raises)."""
        return self._store.get_last_speaker()

    async def remember_speaker(self, name: str, mac: str) -> None:
        """BT-06: delegate to BtDeviceStore (D-01 single-slot overwrite)."""
        self._store.save_last_speaker(name, mac)

    # ------------------------------------------------------------------
    # Pair / Connect / Disconnect / Forget (BT-02/04/05/03).
    #
    # Each public method wraps ONE private async seam in try/except →
    # ``{"ok": False, "error": type(exc).__name__}`` (never 500 — wifi router
    # precedent, RESEARCH line 324, threat T-26-05). The seams hide the full
    # dbus object graph so tests patch ONE attribute per method (Pitfall 6).
    # Routing is delegated to ``bt_audio`` so pactl never appears in tests.
    # ------------------------------------------------------------------

    async def _pair_device(self, bus, mac: str) -> None:
        """Pair + Trust + Connect on ``bus`` (BT-02 + Trusted + BT-04).

        Pitfall 1: runs on the SAME bus the caller used for
        ``register_agent`` so BlueZ routes the pairing handshake to our agent.
        Builds the device object path defensively from the validated MAC
        (Pitfall 5). Treats ``org.bluez.Error.AlreadyExists`` from Pair as
        success (device already paired — RESEARCH line 243).
        """
        path = _device_path(mac)
        intro = await bus.introspect(_BLUEZ_SERVICE, path)
        obj = bus.get_proxy_object(_BLUEZ_SERVICE, path, intro)
        dev = obj.get_interface("org.bluez.Device1")
        props = obj.get_interface("org.freedesktop.DBus.Properties")
        try:
            await dev.call_pair()
        except Exception as exc:
            # AlreadyExists == already paired: not an error (RESEARCH line 243).
            if "AlreadyExists" not in type(exc).__name__:
                raise
        # Belt-and-suspenders with the agent's AuthorizeService (Pitfall 2):
        # trusting the device auto-authorizes future A2DP service connections.
        await props.call_set("org.bluez.Device1", "Trusted", _variant_wrap(True))
        await dev.call_connect()

    async def pair(self, mac: str, name: str | None = None) -> dict:
        """BT-02: register the headless agent, pair+trust+connect, route, remember.

        Holds ONE system ``MessageBus`` for the whole pair sequence (Pitfall 1)
        so ``register_agent`` and ``Device1.Pair`` share a connection. On
        success: persists the speaker via ``remember_speaker`` and routes audio
        to the BT sink via ``bt_audio.route_to_bt`` (AUDIO-06/01).
        """
        try:
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            try:
                await register_agent(bus)
                await self._pair_device(bus, mac)
            finally:
                bus.disconnect()
            await self.remember_speaker(name or mac, mac)
            await bt_audio.route_to_bt(mac)
            self._connected_mac = mac
            self._current_sink = "bt"
            return {"ok": True}
        except Exception as exc:
            _log_event("bt_pair_failed", reason=type(exc).__name__)
            return {"ok": False, "error": type(exc).__name__}

    async def _connect_device(self, bus, mac: str) -> None:
        """Connect an already-paired device (BT-04)."""
        path = _device_path(mac)
        intro = await bus.introspect(_BLUEZ_SERVICE, path)
        obj = bus.get_proxy_object(_BLUEZ_SERVICE, path, intro)
        dev = obj.get_interface("org.bluez.Device1")
        await dev.call_connect()

    async def connect(self, mac: str) -> dict:
        """BT-04: connect a known speaker + route audio to BT."""
        try:
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            try:
                await self._connect_device(bus, mac)
            finally:
                bus.disconnect()
            await bt_audio.route_to_bt(mac)
            self._connected_mac = mac
            self._current_sink = "bt"
            return {"ok": True}
        except Exception as exc:
            _log_event("bt_connect_failed", reason=type(exc).__name__)
            return {"ok": False, "error": type(exc).__name__}

    async def _disconnect_device(self, bus, mac: str) -> None:
        """Disconnect the currently connected device (BT-05)."""
        path = _device_path(mac)
        intro = await bus.introspect(_BLUEZ_SERVICE, path)
        obj = bus.get_proxy_object(_BLUEZ_SERVICE, path, intro)
        dev = obj.get_interface("org.bluez.Device1")
        await dev.call_disconnect()

    async def disconnect(self, mac: str | None = None) -> dict:
        """BT-05 / AUDIO-02: disconnect + fall back to the wired sink."""
        try:
            target = mac or self._connected_mac
            if target is not None:
                bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
                try:
                    await self._disconnect_device(bus, target)
                finally:
                    bus.disconnect()
            await bt_audio.route_to_wired()
            self._connected_mac = None
            self._current_sink = "wired"
            return {"ok": True}
        except Exception as exc:
            _log_event("bt_disconnect_failed", reason=type(exc).__name__)
            return {"ok": False, "error": type(exc).__name__}

    async def _forget_device(self, bus, mac: str) -> None:
        """RemoveDevice on the adapter (BT-03) — needs the device object path."""
        path = _device_path(mac)
        adapter_intro = await bus.introspect(_BLUEZ_SERVICE, _ADAPTER_PATH)
        adapter_obj = bus.get_proxy_object(_BLUEZ_SERVICE, _ADAPTER_PATH, adapter_intro)
        adapter = adapter_obj.get_interface("org.bluez.Adapter1")
        await adapter.call_remove_device(path)

    async def forget(self, mac: str) -> dict:
        """BT-03: remove the device from BlueZ, clear memory + wired fallback.

        Memory is cleared ONLY when the forgotten MAC matches the stored
        speaker (Open Question 2). Falls back to the wired sink only when the
        forgotten MAC was the connected one.
        """
        try:
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            try:
                await self._forget_device(bus, mac)
            finally:
                bus.disconnect()
            stored = self._store.get_last_speaker()
            if stored is not None and stored.get("mac") == mac:
                self._store.clear()
            if self._connected_mac == mac:
                await bt_audio.route_to_wired()
                self._connected_mac = None
                self._current_sink = "wired"
            return {"ok": True}
        except Exception as exc:
            _log_event("bt_forget_failed", reason=type(exc).__name__)
            return {"ok": False, "error": type(exc).__name__}

    async def get_status(self) -> dict:
        """HardwareService Protocol status dict (PLAT-03, Pitfall 7).

        ``connected_mac`` + ``sink`` mirror MockBtManager's shape so the router
        composes one response and tests pass under Mock.
        """
        return {
            "name": "bt",
            "is_mock": False,
            "status": "ok",
            "connected_mac": self._connected_mac,
            "sink": self._current_sink,
        }


def _device_path(mac: str) -> str:
    """Build the BlueZ Device1 object path from a validated MAC (Pitfall 5).

    ``AA:BB:CC:00:11:22`` → ``/org/bluez/hci0/dev_AA_BB_CC_00_11_22``.
    Defensive: the pydantic request model (plan 03) already enforces the
    ``^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$`` shape, but we never trust
    callers — a non-conforming MAC must not produce a traversable path.
    """
    import re

    if not re.fullmatch(r"([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", mac):
        raise ValueError(f"invalid MAC: {mac!r}")
    return f"{_ADAPTER_PATH}/dev_{mac.upper().replace(':', '_')}"


def _variant_wrap(value):  # pragma: no cover — exercised on hardware only
    """Wrap a Python value in a dbus-fast Variant for Properties.Set calls.

    Imported lazily so the module stays importable where dbus-fast is absent.
    Used only on the hardware path (Pitfall 5 power-on); tests do not reach it.
    """
    from dbus_fast import Variant

    return Variant("b", value)


class MockBtManager(BtManager):
    """Mock Bluetooth manager for testing without BT hardware (TEST-BT-01).

    D-10: ``scan()`` returns a deterministic fixed list of audio devices.
    D-11: starts with one already-paired speaker so the reconnect-target read
    path is testable end-to-end without a pairing step. Mirrors
    MockWifiManager's fixed-list style + MockPrinterService's __init__ seeding.
    """

    is_mock: bool = True

    # D-10: deterministic, RSSI-sorted (strongest first). Mock MAC/name strings
    # are at Claude's discretion per CONTEXT — NOT the real classroom MAC.
    _MOCK_SCAN: list[dict] = [
        {"name": "Mock JBL", "mac": "AA:BB:CC:00:11:22", "rssi": -45},
        {"name": "Mock Bose", "mac": "DD:EE:FF:33:44:55", "rssi": -67},
    ]

    def __init__(self) -> None:
        # D-11: pre-seed one paired speaker so get_last_speaker is testable.
        self._last: dict | None = {
            "name": "Mock JBL",
            "mac": "AA:BB:CC:00:11:22",
            "last_connected": "2026-06-12T17:00:00+00:00",
        }
        # Lifecycle state (RESEARCH Pattern 4 lines 300-303). AUDIO-02 default
        # is the wired sink; pair/connect flip to "bt", disconnect/forget fall
        # back to "wired" (TEST-BT-03 fallback target, line 325).
        self._connected_mac: str | None = None
        self._current_sink = "wired"

    async def scan(self) -> list[dict]:
        # Return a fresh list so callers can't mutate the class constant.
        return [dict(entry) for entry in self._MOCK_SCAN]

    async def get_last_speaker(self) -> dict | None:
        # Return a copy so callers can't mutate internal state.
        return dict(self._last) if self._last is not None else None

    async def remember_speaker(self, name: str, mac: str) -> None:
        # D-01: single-slot overwrite (N=1).
        self._last = {
            "name": name,
            "mac": mac,
            "last_connected": datetime.now(timezone.utc).isoformat(),
        }

    async def pair(self, mac: str, name: str | None = None) -> dict:
        """BT-02: pair + remember + connect. Mock sets state in one step."""
        self._connected_mac = mac
        self._current_sink = "bt"
        await self.remember_speaker(name or "Mock Speaker", mac)
        return {"ok": True}

    async def connect(self, mac: str) -> dict:
        """BT-04: connect an already-paired speaker (Mock sets state)."""
        self._connected_mac = mac
        self._current_sink = "bt"
        return {"ok": True}

    async def disconnect(self, mac: str | None = None) -> dict:
        """BT-05 / AUDIO-02 / TEST-BT-03: disconnect → wired fallback."""
        self._connected_mac = None
        self._current_sink = "wired"
        return {"ok": True}

    async def forget(self, mac: str) -> dict:
        """BT-03: forget a speaker. Clears memory; wired fallback only when
        the forgotten MAC was the connected one (Open Question 2).
        """
        if self._connected_mac == mac:
            self._connected_mac = None
            self._current_sink = "wired"
        # Clear remembered speaker only when forgotten MAC == stored MAC
        # (Open Question 2 — don't wipe a different speaker's memory).
        if self._last is not None and self._last.get("mac") == mac:
            self._last = None
        return {"ok": True}

    async def get_status(self) -> dict:
        return {
            "name": "bt",
            "is_mock": True,
            "status": "ok",
            "connected_mac": self._connected_mac,
            "sink": self._current_sink,
        }


def create_bt_manager() -> BtManager:
    """Factory — never raises (PLAT-03, mirrors printer_handler.py).

    Returns:
        - MockBtManager when ``TESTING`` env is set.
        - MockBtManager when ``dbus_fast`` import failed (logs
          ``bt_init_fallback`` with ``reason="dbus_fast_unavailable"``).
        - MockBtManager when no BT adapter is present (logs
          ``bt_init_fallback`` with ``reason="no_adapter"``).
        - RealBtManager otherwise.

    Every fallback returns a usable manager; this function never raises.
    """
    if os.environ.get("TESTING"):
        return MockBtManager()
    if not _DBUS_FAST_AVAILABLE:
        _log_event("bt_init_fallback", reason="dbus_fast_unavailable")
        return MockBtManager()
    if not _bt_adapter_present():
        _log_event("bt_init_fallback", reason="no_adapter")
        return MockBtManager()
    return RealBtManager()
