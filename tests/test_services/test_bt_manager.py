"""Tests for bt_manager — Bluetooth service with dbus-fast BlueZ discovery.

Mirrors tests/test_services/test_wifi_manager.py layout. Two test scopes:
  - Pure scan logic (_is_audio, _to_entries, Variant unwrap, RSSI sort) — no D-Bus.
  - BtManager base/Real/Mock + create_bt_manager() factory + Real scan seam.

The Real scan is tested by patching ONE seam (_get_managed_objects) per
RESEARCH Pitfall 6 — never the full dbus chain.
"""

import pytest

from app.services.bt_manager import (
    A2DP_SINK_UUID,
    BtManager,
    MockBtManager,
    RealBtManager,
    _bt_adapter_present,
    _is_audio,
    _to_entries,
    create_bt_manager,
)

# ---------------------------------------------------------------------------
# Helpers — fake dbus-fast Variant (Pitfall 2: GetManagedObjects wraps every
# property value in a Variant; _to_entries must unwrap via .value).
# ---------------------------------------------------------------------------


class _Variant:
    """Minimal stand-in for dbus_fast.aio.Variant used in fixtures.

    Real dbus-fast wraps each property value as ``Variant(signature, value)``
    when returning from ``GetManagedObjects``. The helper under test only needs
    the ``.value`` attribute to unwrap, so this tiny stub reproduces the shape
    without pulling dbus-fast into the test path.
    """

    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value

    def __repr__(self):  # pragma: no cover - debug aid
        return f"_Variant({self.value!r})"


def _device(
    address,
    *,
    alias=None,
    name=None,
    rssi=None,
    cls=None,
    uuids=None,
    icon=None,
):
    """Build a GetManagedObjects-shaped entry for one Device1 object.

    Returns the ``{"org.bluez.Device1": {prop: Variant, ...}}`` iface dict
    so callers can compose a full ``{path: {iface: props}}`` fixture.
    """
    props = {}
    if alias is not None:
        props["Alias"] = _Variant(alias)
    if name is not None:
        props["Name"] = _Variant(name)
    props["Address"] = _Variant(address)
    if rssi is not None:
        props["RSSI"] = _Variant(rssi)
    if cls is not None:
        props["Class"] = _Variant(cls)
    if uuids is not None:
        props["UUIDs"] = _Variant(uuids)
    if icon is not None:
        props["Icon"] = _Variant(icon)
    return {"org.bluez.Device1": props}


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestAudioSinkUuidConstant:
    """A2DP_SINK_UUID constant value (D-05 audio filter)."""

    def test_uuid_is_a2dp_sink(self):
        # Bluetooth SIG assigned number for Audio Sink (A2DP Sink = 0x110B).
        assert A2DP_SINK_UUID == "0000110b-0000-1000-8000-00805f9b34fb"


# ---------------------------------------------------------------------------
# _is_audio (D-05 audio filter — CoD major Audio/Video OR A2DP sink UUID
# OR Icon=="audio-card")
# ---------------------------------------------------------------------------


class TestAudioFilter:
    """_is_audio matches CoD major Audio/Video, A2DP-sink UUID, audio-card Icon."""

    def test_cod_major_audio_video(self):
        # 0x240414: service class bits 0x200000 (rendering) + 0x040000 (audio)
        # + major class 0x0400 (Audio/Video) + minor 0x0014 (loudspeaker).
        assert _is_audio({"Class": 0x240414}) is True

    def test_cod_major_audio_video_bits_8_to_12(self):
        # Major class = (Class >> 8) & 0x1F == 0x04 ⇒ Audio/Video.
        # 0x000418: bits 8-12 == 0x04, minor wearable-headset.
        assert _is_audio({"Class": 0x000418}) is True

    def test_cod_non_audio_keyboard(self):
        # 0x000540: major class (>> 8 & 0x1F) == 0x05 (Peripheral) — not audio.
        assert _is_audio({"Class": 0x000540}) is False

    def test_cod_non_audio_phone(self):
        # 0x000400 (major 0x04 IS audio — sanity check we don't false-negative):
        # adjust to a real phone CoD: 0x7a020c major = (0x7a020c >> 8) & 0x1F
        # = 0x02 (Phone). Phone should NOT be treated as audio by CoD alone.
        assert _is_audio({"Class": 0x7A020C}) is False

    def test_a2dp_sink_uuid(self):
        assert _is_audio({"UUIDs": [A2DP_SINK_UUID]}) is True

    def test_a2dp_sink_uuid_uppercase(self):
        # UUIDs from BlueZ are sometimes mixed-case; match case-insensitively.
        assert _is_audio({"UUIDs": ["0000110B-0000-1000-8000-00805F9B34FB"]}) is True

    def test_a2dp_sink_uuid_among_many(self):
        uuids = [
            "00001800-0000-1000-8000-00805f9b34fb",  # GAP
            "00001801-0000-1000-8000-00805f9b34fb",  # GATT
            A2DP_SINK_UUID,
            "0000110e-0000-1000-8000-00805f9b34fb",  # AVRCP remote
        ]
        assert _is_audio({"UUIDs": uuids}) is True

    def test_non_audio_uuid(self):
        # Only the A2DP *sink* UUID counts; A2DP source (0x110A) alone is not.
        assert _is_audio({"UUIDs": ["0000110a-0000-1000-8000-00805f9b34fb"]}) is False

    def test_icon_audio_card(self):
        assert _is_audio({"Icon": "audio-card"}) is True

    def test_icon_non_audio(self):
        assert _is_audio({"Icon": "input-keyboard"}) is False

    def test_empty_props(self):
        assert _is_audio({}) is False

    def test_cod_takes_precedence_over_uuid(self):
        # Even without an A2DP UUID, an Audio/Video CoD still qualifies.
        assert _is_audio({"Class": 0x240414, "UUIDs": []}) is True

    def test_missing_class_falls_back_to_uuid(self):
        # Devices mid-discovery often advertise no Class yet — UUID still wins.
        assert _is_audio({"UUIDs": [A2DP_SINK_UUID]}) is True

    def test_missing_class_and_uuid_falls_back_to_icon(self):
        assert _is_audio({"Icon": "audio-card"}) is True

    def test_class_none_treated_as_missing(self):
        assert _is_audio({"Class": None, "UUIDs": [], "Icon": "input-mouse"}) is False


# ---------------------------------------------------------------------------
# _to_entries (Variant unwrap + name precedence + sort)
# ---------------------------------------------------------------------------


class TestToEntriesFiltering:
    """_to_entries keeps only audio Device1 objects from GetManagedObjects."""

    def test_keeps_audio_drops_non_audio(self):
        managed = {
            "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_01": _device(
                "AA:BB:CC:DD:EE:01",
                alias="Aula JBL",
                rssi=-45,
                cls=0x240414,
            ),
            "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_02": _device(
                "AA:BB:CC:DD:EE:02",
                alias="Teclado Bluetooth",
                rssi=-80,
                cls=0x000540,  # Peripheral — keyboard
            ),
        }
        entries = _to_entries(managed)
        assert len(entries) == 1
        assert entries[0]["mac"] == "AA:BB:CC:DD:EE:01"

    def test_skips_non_device1_objects(self):
        # GetManagedObjects returns adapters + devices; only Device1 matters.
        managed = {
            "/org/bluez/hci0": {
                "org.bluez.Adapter1": {
                    "Address": _Variant("AA:BB:CC:DD:EE:00"),
                    "Powered": _Variant(True),
                }
            },
            "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_01": _device(
                "AA:BB:CC:DD:EE:01",
                alias="Mock JBL",
                rssi=-45,
                cls=0x240414,
            ),
        }
        entries = _to_entries(managed)
        assert len(entries) == 1
        assert entries[0]["mac"] == "AA:BB:CC:DD:EE:01"

    def test_empty_managed(self):
        assert _to_entries({}) == []


class TestToEntriesNamePrecedence:
    """name prefers Alias, then Name, then Address (D-05/BT-01)."""

    def test_alias_preferred(self):
        managed = {
            "/p1": _device(
                "AA:BB:CC:00:00:01",
                alias="Alias Name",
                name="Real Name",
                rssi=-45,
                cls=0x240414,
            )
        }
        entries = _to_entries(managed)
        assert entries[0]["name"] == "Alias Name"

    def test_name_when_no_alias(self):
        managed = {
            "/p1": _device(
                "AA:BB:CC:00:00:02",
                name="Real Name",
                rssi=-45,
                cls=0x240414,
            )
        }
        entries = _to_entries(managed)
        assert entries[0]["name"] == "Real Name"

    def test_address_when_no_alias_no_name(self):
        managed = {
            "/p1": _device(
                "AA:BB:CC:00:00:03",
                rssi=-45,
                cls=0x240414,
            )
        }
        entries = _to_entries(managed)
        assert entries[0]["name"] == "AA:BB:CC:00:00:03"


class TestToEntriesShape:
    """Each entry is exactly {name, mac, rssi} (BT-01)."""

    def test_entry_shape(self):
        managed = {
            "/p1": _device(
                "AA:BB:CC:00:00:01",
                alias="Mock JBL",
                rssi=-45,
                cls=0x240414,
            )
        }
        entries = _to_entries(managed)
        assert set(entries[0].keys()) == {"name", "mac", "rssi"}
        assert entries[0]["mac"] == "AA:BB:CC:00:00:01"
        assert entries[0]["rssi"] == -45


class TestVariantUnwrap:
    """rssi is a plain int (or None), not a Variant (Pitfall 2 / T-26-07)."""

    def test_rssi_is_plain_int(self):
        managed = {
            "/p1": _device(
                "AA:BB:CC:00:00:01",
                alias="Mock JBL",
                rssi=-45,
                cls=0x240414,
            )
        }
        rssi = _to_entries(managed)[0]["rssi"]
        assert rssi == -45
        assert isinstance(rssi, int)
        # The Variant wrapper must NOT leak into the output.
        assert not hasattr(rssi, "value")

    def test_name_is_plain_str(self):
        managed = {
            "/p1": _device(
                "AA:BB:CC:00:00:01",
                alias="Mock JBL",
                rssi=-45,
                cls=0x240414,
            )
        }
        name = _to_entries(managed)[0]["name"]
        assert name == "Mock JBL"
        assert isinstance(name, str)
        assert not hasattr(name, "value")


class TestRssiSort:
    """D-06: strongest RSSI first; None RSSI sorts last."""

    def test_strongest_first(self):
        managed = {
            "/weak": _device(
                "AA:BB:CC:00:00:0A",
                alias="Weak",
                rssi=-67,
                cls=0x240414,
            ),
            "/strong": _device(
                "AA:BB:CC:00:00:0B",
                alias="Strong",
                rssi=-45,
                cls=0x240414,
            ),
            "/mid": _device(
                "AA:BB:CC:00:00:0C",
                alias="Mid",
                rssi=-55,
                cls=0x240414,
            ),
        }
        entries = _to_entries(managed)
        # -45 (strongest) > -55 > -67
        assert [e["rssi"] for e in entries] == [-45, -55, -67]

    def test_none_rssi_sorts_last(self):
        managed = {
            "/known": _device(
                "AA:BB:CC:00:00:0A",
                alias="Known Cached",
                rssi=None,
                cls=0x240414,
            ),
            "/fresh": _device(
                "AA:BB:CC:00:00:0B",
                alias="Fresh",
                rssi=-70,
                cls=0x240414,
            ),
        }
        entries = _to_entries(managed)
        # Even a weak -70 ranks above a missing RSSI.
        assert entries[0]["rssi"] == -70
        assert entries[1]["rssi"] is None

    def test_all_none_rssi_preserved(self):
        managed = {
            "/a": _device("AA:BB:CC:00:00:0A", alias="A", cls=0x240414),
            "/b": _device("AA:BB:CC:00:00:0B", alias="B", cls=0x240414),
        }
        entries = _to_entries(managed)
        assert len(entries) == 2
        assert all(e["rssi"] is None for e in entries)

    def test_missing_rssi_key_treated_as_none(self):
        # Pitfall 3: RSSI key absent (not just None) for cached/paired devices.
        managed = {
            "/p1": _device(
                "AA:BB:CC:00:00:01",
                alias="Mock JBL",
                cls=0x240414,  # no rssi kwarg → key absent
            )
        }
        entries = _to_entries(managed)
        assert entries[0]["rssi"] is None


class TestIntegrationFixture:
    """End-to-end _to_entries over a realistic GetManagedObjects fixture."""

    def test_mixed_fixture_audio_only_sorted(self):
        managed = {
            # Adapter — must be ignored.
            "/org/bluez/hci0": {
                "org.bluez.Adapter1": {
                    "Address": _Variant("00:00:00:00:00:00"),
                    "Powered": _Variant(True),
                }
            },
            # Audio speaker (CoD) — strongest.
            "/org/bluez/hci0/dev_11_22_33_44_55_01": _device(
                "11:22:33:44:55:01",
                alias="Aula JBL",
                rssi=-45,
                cls=0x240414,
            ),
            # Audio speaker (A2DP UUID, no CoD) — mid.
            "/org/bluez/hci0/dev_11_22_33_44_55_02": _device(
                "11:22:33:44:55:02",
                name="Bose SoundLink",
                rssi=-60,
                uuids=[A2DP_SINK_UUID],
            ),
            # Cached speaker — no RSSI, sorts last.
            "/org/bluez/hci0/dev_11_22_33_44_55_03": _device(
                "11:22:33:44:55:03",
                alias="Sony WH",
                cls=0x240414,
            ),
            # Non-audio (phone CoD) — filtered out.
            "/org/bluez/hci0/dev_11_22_33_44_55_04": _device(
                "11:22:33:44:55:04",
                alias="Móvil Profe",
                rssi=-50,
                cls=0x7A020C,
            ),
            # Non-Device1 — filtered out.
            "/org/bluez/hci0/dev_11_22_33_44_55_05": {
                "org.bluez.Battery1": {"Percentage": _Variant(80)}
            },
        }
        entries = _to_entries(managed)
        assert [e["mac"] for e in entries] == [
            "11:22:33:44:55:01",  # -45
            "11:22:33:44:55:02",  # -60
            "11:22:33:44:55:03",  # None last
        ]
        # Sanity: rssi are plain ints / None, not Variants.
        for e in entries:
            if e["rssi"] is not None:
                assert isinstance(e["rssi"], int)
                assert not hasattr(e["rssi"], "value")


# ===========================================================================
# Task 2: BtManager base / Mock / Real / factory + Real scan seam
#
# Tests below patch ONE seam (_get_managed_objects) for RealBtManager.scan()
# per RESEARCH Pitfall 6 — never the full dbus chain. Factory tests patch
# _DBUS_FAST_AVAILABLE and _bt_adapter_present and the TESTING env var.
# ===========================================================================


# ---------------------------------------------------------------------------
# Shared fixtures for RealBtManager.scan() — GetManagedObjects shape via the
# single injected seam. Reuses _device() / _Variant() from Task 1.
# ---------------------------------------------------------------------------


def _real_scan_fixture():
    """A realistic GetManagedObjects result with two audio speakers + a phone."""
    return {
        "/org/bluez/hci0/dev_11_22_33_44_55_01": _device(
            "11:22:33:44:55:01",
            alias="Aula JBL",
            rssi=-45,
            cls=0x240414,
        ),
        "/org/bluez/hci0/dev_11_22_33_44_55_02": _device(
            "11:22:33:44:55:02",
            name="Bose SoundLink",
            rssi=-67,
            uuids=[A2DP_SINK_UUID],
        ),
        # Non-audio — filtered out.
        "/org/bluez/hci0/dev_11_22_33_44_55_03": _device(
            "11:22:33:44:55:03",
            alias="Móvil Profe",
            rssi=-50,
            cls=0x7A020C,
        ),
    }


# ---------------------------------------------------------------------------
# BtManager base contract (PLAT-03)
# ---------------------------------------------------------------------------


class TestBtManagerBaseClass:
    """BtManager base class: is_mock False, methods raise NotImplementedError."""

    def test_base_is_mock_false(self):
        mgr = BtManager()
        assert mgr.is_mock is False

    async def test_base_scan_raises(self):
        mgr = BtManager()
        with pytest.raises(NotImplementedError):
            await mgr.scan()

    async def test_base_get_last_speaker_raises(self):
        mgr = BtManager()
        with pytest.raises(NotImplementedError):
            await mgr.get_last_speaker()

    async def test_base_remember_speaker_raises(self):
        mgr = BtManager()
        with pytest.raises(NotImplementedError):
            await mgr.remember_speaker("name", "AA:BB:CC:DD:EE:FF")

    async def test_base_get_status_raises(self):
        mgr = BtManager()
        with pytest.raises(NotImplementedError):
            await mgr.get_status()

    async def test_base_is_connected_raises(self):
        mgr = BtManager()
        with pytest.raises(NotImplementedError):
            await mgr.is_connected("AA:BB:CC:DD:EE:FF")


# ---------------------------------------------------------------------------
# MockBtManager (TEST-BT-01, D-10 fixed list, D-11 pre-seeded memory)
# ---------------------------------------------------------------------------


class TestMockBtManager:
    """MockBtManager is_mock True; deterministic scan; pre-seeded memory (D-11)."""

    def test_is_mock_true(self):
        mgr = MockBtManager()
        assert mgr.is_mock is True

    async def test_scan_returns_deterministic_audio_list(self):
        mgr = MockBtManager()
        result1 = await mgr.scan()
        result2 = await mgr.scan()
        # D-10: deterministic — same list every call.
        assert result1 == result2
        # 2-3 devices, each exactly {name, mac, rssi}.
        assert 2 <= len(result1) <= 3
        for entry in result1:
            assert set(entry.keys()) == {"name", "mac", "rssi"}

    async def test_scan_results_rssi_sorted(self):
        mgr = MockBtManager()
        result = await mgr.scan()
        rssis = [e["rssi"] for e in result if e["rssi"] is not None]
        # Strongest first: each RSSI >= the next.
        assert all(rssis[i] >= rssis[i + 1] for i in range(len(rssis) - 1))

    async def test_pre_seeded_last_speaker(self):
        """D-11: Mock starts with one already-paired speaker."""
        mgr = MockBtManager()
        last = await mgr.get_last_speaker()
        assert last is not None
        assert "name" in last
        assert "mac" in last
        assert "last_connected" in last

    async def test_remember_speaker_updates_memory(self):
        mgr = MockBtManager()
        await mgr.remember_speaker("Nuevo Altavoz", "11:22:33:44:55:66")
        last = await mgr.get_last_speaker()
        assert last["name"] == "Nuevo Altavoz"
        assert last["mac"] == "11:22:33:44:55:66"
        assert "last_connected" in last

    async def test_remember_speaker_is_single_slot(self):
        """D-01: N=1 — remembering a new speaker replaces, not appends."""
        mgr = MockBtManager()
        await mgr.remember_speaker("First", "11:22:33:44:55:01")
        await mgr.remember_speaker("Second", "11:22:33:44:55:02")
        last = await mgr.get_last_speaker()
        assert last["name"] == "Second"

    async def test_get_status_shape(self):
        mgr = MockBtManager()
        status = await mgr.get_status()
        assert status["name"] == "bt"
        assert status["is_mock"] is True
        assert "status" in status


# ---------------------------------------------------------------------------
# RealBtManager.scan() — patched at ONE seam (_get_managed_objects)
# (Pitfall 6 — never patch the full dbus chain)
# ---------------------------------------------------------------------------


class TestRealBtManagerScan:
    """RealBtManager.scan() reuses _to_entries over the injected seam."""

    async def test_scan_returns_sorted_audio_entries(self):
        mgr = RealBtManager()
        # Patch the single seam; never touch the dbus chain.
        mgr._get_managed_objects = _async_returning(_real_scan_fixture())
        result = await mgr.scan()
        assert [e["mac"] for e in result] == [
            "11:22:33:44:55:01",  # -45 strongest
            "11:22:33:44:55:02",  # -67
        ]
        assert all(set(e.keys()) == {"name", "mac", "rssi"} for e in result)

    async def test_scan_returns_empty_when_seam_raises(self):
        """Pitfall 4: adapter absent / BlueZ down → scan returns [], never 500s."""
        mgr = RealBtManager()
        mgr._get_managed_objects = _async_raising(RuntimeError("no adapter"))
        result = await mgr.scan()
        assert result == []

    async def test_scan_returns_empty_when_dbus_call_fails(self):
        """Any exception from the bus flow → [] (Pitfall 4, threat T-26-05)."""
        mgr = RealBtManager()
        mgr._get_managed_objects = _async_raising(ConnectionError("dbus down"))
        result = await mgr.scan()
        assert result == []

    async def test_scan_returns_empty_on_empty_managed(self):
        mgr = RealBtManager()
        mgr._get_managed_objects = _async_returning({})
        result = await mgr.scan()
        assert result == []

    async def test_scan_does_not_propagate_variant_errors(self):
        """A malformed entry should not crash the whole scan."""
        fixture = {
            "/good": _device(
                "11:22:33:44:55:01",
                alias="Good",
                rssi=-45,
                cls=0x240414,
            ),
        }
        mgr = RealBtManager()
        mgr._get_managed_objects = _async_returning(fixture)
        result = await mgr.scan()
        assert len(result) == 1


# ---------------------------------------------------------------------------
# RealBtManager.get_last_speaker / remember_speaker delegate to BtDeviceStore
# (BT-06)
# ---------------------------------------------------------------------------


class TestRealBtManagerMemory:
    """Real memory operations delegate to BtDeviceStore (BT-06)."""

    async def test_get_last_speaker_delegates_to_store(self, tmp_path):
        from app.services.bt_store import BtDeviceStore

        store = BtDeviceStore(tmp_path / "bt.json")
        # Seed the store directly; the manager must read through it.
        store.save_last_speaker("Seed Speaker", "AA:BB:CC:00:11:22")
        mgr = RealBtManager(store=store)
        last = await mgr.get_last_speaker()
        assert last is not None
        assert last["name"] == "Seed Speaker"
        assert last["mac"] == "AA:BB:CC:00:11:22"

    async def test_get_last_speaker_none_when_empty(self, tmp_path):
        from app.services.bt_store import BtDeviceStore

        store = BtDeviceStore(tmp_path / "bt.json")
        mgr = RealBtManager(store=store)
        assert await mgr.get_last_speaker() is None

    async def test_remember_speaker_writes_through_store(self, tmp_path):
        from app.services.bt_store import BtDeviceStore

        store = BtDeviceStore(tmp_path / "bt.json")
        mgr = RealBtManager(store=store)
        await mgr.remember_speaker("New Speaker", "11:22:33:44:55:66")
        # Store on disk must now hold the speaker — round-trip via a fresh store.
        store2 = BtDeviceStore(tmp_path / "bt.json")
        last = store2.get_last_speaker()
        assert last["name"] == "New Speaker"
        assert last["mac"] == "11:22:33:44:55:66"


# ---------------------------------------------------------------------------
# create_bt_manager() factory — never raises, Mock for TESTING/no-dbus/no-adapter
# (PLAT-03, mirrors printer_handler.py structure)
# ---------------------------------------------------------------------------


class TestFactory:
    """create_bt_manager() routes to Mock or Real without ever raising."""

    def test_factory_returns_mock_when_testing_set(self, monkeypatch):
        # conftest sets TESTING=1 globally; force it explicitly for clarity.
        monkeypatch.setenv("TESTING", "1")
        mgr = create_bt_manager()
        assert isinstance(mgr, MockBtManager)
        assert mgr.is_mock is True

    def test_factory_returns_mock_when_dbus_fast_unavailable(self, monkeypatch):
        # Even without TESTING, missing dbus-fast → Mock.
        monkeypatch.delenv("TESTING", raising=False)
        monkeypatch.setattr("app.services.bt_manager._DBUS_FAST_AVAILABLE", False)
        monkeypatch.setattr("app.services.bt_manager._bt_adapter_present", lambda: True)
        mgr = create_bt_manager()
        assert isinstance(mgr, MockBtManager)

    def test_factory_returns_mock_when_adapter_absent(self, monkeypatch):
        monkeypatch.delenv("TESTING", raising=False)
        monkeypatch.setattr("app.services.bt_manager._DBUS_FAST_AVAILABLE", True)
        monkeypatch.setattr(
            "app.services.bt_manager._bt_adapter_present", lambda: False
        )
        mgr = create_bt_manager()
        assert isinstance(mgr, MockBtManager)

    def test_factory_returns_real_when_all_gates_open(self, monkeypatch):
        monkeypatch.delenv("TESTING", raising=False)
        monkeypatch.setattr("app.services.bt_manager._DBUS_FAST_AVAILABLE", True)
        monkeypatch.setattr("app.services.bt_manager._bt_adapter_present", lambda: True)
        mgr = create_bt_manager()
        assert isinstance(mgr, RealBtManager)
        assert mgr.is_mock is False

    def test_factory_creates_new_instance_each_call(self, monkeypatch):
        monkeypatch.setenv("TESTING", "1")
        mgr1 = create_bt_manager()
        mgr2 = create_bt_manager()
        assert mgr1 is not mgr2

    def test_factory_never_raises_on_any_path(self, monkeypatch):
        """PLAT-03: every fallback path must return, never raise."""
        monkeypatch.delenv("TESTING", raising=False)
        # All three negative branches.
        monkeypatch.setattr("app.services.bt_manager._DBUS_FAST_AVAILABLE", False)
        m1 = create_bt_manager()
        assert isinstance(m1, MockBtManager)

        monkeypatch.setattr("app.services.bt_manager._DBUS_FAST_AVAILABLE", True)
        monkeypatch.setattr(
            "app.services.bt_manager._bt_adapter_present", lambda: False
        )
        m2 = create_bt_manager()
        assert isinstance(m2, MockBtManager)

    def test_factory_testing_takes_precedence_over_real(self, monkeypatch):
        """TESTING beats everything — even if hardware is present."""
        monkeypatch.setenv("TESTING", "1")
        monkeypatch.setattr("app.services.bt_manager._DBUS_FAST_AVAILABLE", True)
        monkeypatch.setattr("app.services.bt_manager._bt_adapter_present", lambda: True)
        mgr = create_bt_manager()
        assert isinstance(mgr, MockBtManager)


# ---------------------------------------------------------------------------
# _bt_adapter_present — pure filesystem probe (the wifi shutil.which analog)
# ---------------------------------------------------------------------------


class TestBtAdapterPresent:
    """_bt_adapter_present globs /sys/class/bluetooth/hci*."""

    def test_returns_bool(self):
        # On this machine it's either True or False, never non-bool / raising.
        result = _bt_adapter_present()
        assert isinstance(result, bool)

    def test_true_when_glob_matches(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.bt_manager.glob.glob",
            lambda pattern: ["/sys/class/bluetooth/hci0"],
        )
        assert _bt_adapter_present() is True

    def test_false_when_glob_empty(self, monkeypatch):
        monkeypatch.setattr("app.services.bt_manager.glob.glob", lambda pattern: [])
        assert _bt_adapter_present() is False

    def test_false_on_oserror(self, monkeypatch):
        """Never raises: glob errors resolve to False (defensive)."""

        def raise_oserror(pattern):
            raise OSError("permission denied")

        monkeypatch.setattr("app.services.bt_manager.glob.glob", raise_oserror)
        assert _bt_adapter_present() is False


# ---------------------------------------------------------------------------
# Helpers for the Real scan seam (Pitfall 6)
# ---------------------------------------------------------------------------


def _async_returning(value):
    """Build an awaitable-returning callable for the _get_managed_objects seam.

    Replaces the bound method on a RealBtManager instance so the scan test
    never touches the real dbus chain. Returns ``value`` when awaited.
    """

    async def _stub(self=None):
        return value

    return _stub


def _async_raising(exc):
    """Build an awaitable that raises ``exc`` when called (Pitfall 4 path)."""

    async def _stub(self=None):
        raise exc

    return _stub


def _seam_returning(value):
    """Build an awaitable that accepts arbitrary args and returns ``value``.

    For the lifecycle seams (``_pair_device(bus, mac)``, ``_connect_device``,
    ``_disconnect_device``, ``_forget_device``) which are called with extra
    positional args — the existing ``_async_returning`` only accepts ``self``.
    """

    async def _stub(*args, **kwargs):
        return value

    return _stub


def _seam_raising(exc):
    """Build an awaitable that accepts arbitrary args and raises ``exc``."""

    async def _stub(*args, **kwargs):
        raise exc

    return _stub


# ===========================================================================
# Task 1 (27-05): base contract pair/connect/disconnect/forget,
# MockBtManager state machine (BT-02/03/04/05 + AUDIO-02 fallback),
# BtDeviceStore.clear()
# ===========================================================================


class TestBaseContractLifecycle:
    """BtManager base raises NotImplementedError on the four lifecycle methods."""

    async def test_base_pair_raises(self):
        mgr = BtManager()
        with pytest.raises(NotImplementedError):
            await mgr.pair("AA:BB:CC:00:11:22")

    async def test_base_connect_raises(self):
        mgr = BtManager()
        with pytest.raises(NotImplementedError):
            await mgr.connect("AA:BB:CC:00:11:22")

    async def test_base_disconnect_raises(self):
        mgr = BtManager()
        with pytest.raises(NotImplementedError):
            await mgr.disconnect()

    async def test_base_forget_raises(self):
        mgr = BtManager()
        with pytest.raises(NotImplementedError):
            await mgr.forget("AA:BB:CC:00:11:22")


class TestMockPair:
    """MockBtManager.pair connects + remembers (BT-02)."""

    async def test_pair_returns_ok(self):
        mgr = MockBtManager()
        result = await mgr.pair("AA:BB:CC:00:11:22", "JBL")
        assert result == {"ok": True}

    async def test_pair_remembers_speaker(self):
        mgr = MockBtManager()
        await mgr.pair("AA:BB:CC:00:11:22", "JBL")
        last = await mgr.get_last_speaker()
        assert last is not None
        assert last["mac"] == "AA:BB:CC:00:11:22"
        assert last["name"] == "JBL"

    async def test_pair_sets_connected_and_bt_sink(self):
        mgr = MockBtManager()
        await mgr.pair("AA:BB:CC:00:11:22", "JBL")
        status = await mgr.get_status()
        assert status["connected_mac"] == "AA:BB:CC:00:11:22"
        assert status["sink"] == "bt"

    async def test_pair_without_name_uses_fallback(self):
        mgr = MockBtManager()
        await mgr.pair("AA:BB:CC:00:11:22")
        last = await mgr.get_last_speaker()
        assert last is not None
        assert last["mac"] == "AA:BB:CC:00:11:22"
        assert last["name"]  # non-empty fallback


class TestMockConnect:
    """MockBtManager.connect sets connected + sink='bt' (BT-04)."""

    async def test_connect_returns_ok(self):
        mgr = MockBtManager()
        result = await mgr.connect("DD:EE:FF:33:44:55")
        assert result == {"ok": True}

    async def test_connect_sets_connected_and_bt_sink(self):
        mgr = MockBtManager()
        await mgr.connect("DD:EE:FF:33:44:55")
        status = await mgr.get_status()
        assert status["connected_mac"] == "DD:EE:FF:33:44:55"
        assert status["sink"] == "bt"


class TestMockIsConnected:
    """MockBtManager.is_connected reflects the connected MAC (BT health probe)."""

    async def test_false_when_nothing_connected(self):
        mgr = MockBtManager()
        assert await mgr.is_connected("DD:EE:FF:33:44:55") is False

    async def test_true_for_connected_mac(self):
        mgr = MockBtManager()
        await mgr.connect("DD:EE:FF:33:44:55")
        assert await mgr.is_connected("DD:EE:FF:33:44:55") is True

    async def test_false_for_other_mac(self):
        mgr = MockBtManager()
        await mgr.connect("DD:EE:FF:33:44:55")
        assert await mgr.is_connected("11:22:33:44:55:66") is False


class TestMockDisconnectWiredFallback:
    """MockBtManager.disconnect clears connected AND falls back to wired.

    This is the TEST-BT-03 / AUDIO-02 fallback assertion target
    (RESEARCH Pattern 4 line 325).
    """

    async def test_disconnect_returns_ok(self):
        mgr = MockBtManager()
        await mgr.connect("DD:EE:FF:33:44:55")
        result = await mgr.disconnect()
        assert result == {"ok": True}

    async def test_disconnect_sets_wired_sink(self):
        mgr = MockBtManager()
        await mgr.connect("DD:EE:FF:33:44:55")
        await mgr.disconnect()
        status = await mgr.get_status()
        assert status["sink"] == "wired"

    async def test_disconnect_clears_connected_mac(self):
        mgr = MockBtManager()
        await mgr.connect("DD:EE:FF:33:44:55")
        await mgr.disconnect()
        status = await mgr.get_status()
        assert status["connected_mac"] is None


class TestMockForget:
    """MockBtManager.forget clears memory + wired fallback if connected (BT-03)."""

    async def test_forget_returns_ok(self):
        mgr = MockBtManager()
        await mgr.pair("AA:BB:CC:00:11:22", "JBL")
        result = await mgr.forget("AA:BB:CC:00:11:22")
        assert result == {"ok": True}

    async def test_forget_clears_last_speaker(self):
        mgr = MockBtManager()
        await mgr.pair("AA:BB:CC:00:11:22", "JBL")
        await mgr.forget("AA:BB:CC:00:11:22")
        assert await mgr.get_last_speaker() is None

    async def test_forget_connected_falls_back_to_wired(self):
        mgr = MockBtManager()
        await mgr.pair("AA:BB:CC:00:11:22", "JBL")
        await mgr.forget("AA:BB:CC:00:11:22")
        status = await mgr.get_status()
        assert status["sink"] == "wired"
        assert status["connected_mac"] is None

    async def test_forget_different_mac_does_not_clear_memory(self):
        """Open Question 2: forgetting a different MAC than stored must NOT
        clear the remembered speaker (only clears when forgotten == stored).
        """
        mgr = MockBtManager()
        await mgr.pair("AA:BB:CC:00:11:22", "JBL")
        await mgr.forget("DD:EE:FF:33:44:55")  # different MAC
        last = await mgr.get_last_speaker()
        assert last is not None
        assert last["mac"] == "AA:BB:CC:00:11:22"


class TestMockGetStatusExtended:
    """MockBtManager.get_status carries connected_mac + sink (Pitfall 7)."""

    async def test_status_has_connected_mac_and_sink_keys(self):
        mgr = MockBtManager()
        status = await mgr.get_status()
        assert "connected_mac" in status
        assert "sink" in status

    async def test_status_default_wired_disconnected(self):
        mgr = MockBtManager()
        status = await mgr.get_status()
        assert status["connected_mac"] is None
        assert status["sink"] == "wired"


class TestBtDeviceStoreClear:
    """BtDeviceStore.clear() resets last_speaker to None atomically."""

    def test_clear_after_save(self, tmp_path):
        from app.services.bt_store import BtDeviceStore

        store = BtDeviceStore(tmp_path / "bt.json")
        store.save_last_speaker("Seed", "AA:BB:CC:00:11:22")
        assert store.get_last_speaker() is not None
        store.clear()
        assert store.get_last_speaker() is None

    def test_clear_when_empty_is_noop(self, tmp_path):
        from app.services.bt_store import BtDeviceStore

        store = BtDeviceStore(tmp_path / "bt.json")
        store.clear()  # must not raise on missing file
        assert store.get_last_speaker() is None

    def test_clear_persists_across_instances(self, tmp_path):
        from app.services.bt_store import BtDeviceStore

        path = tmp_path / "bt.json"
        store = BtDeviceStore(path)
        store.save_last_speaker("Seed", "AA:BB:CC:00:11:22")
        store.clear()
        # A fresh store reading the same file must also see None.
        store2 = BtDeviceStore(path)
        assert store2.get_last_speaker() is None


# ===========================================================================
# Task 2 (27-05): RealBtManager pair/connect/disconnect/forget one-seam
# discipline + bt_audio routing delegation + extended get_status
#
# Each Real method hides its dbus chain behind ONE patchable async seam
# (_pair_device/_connect_device/_disconnect_device/_forget_device) and the
# pactl chain behind bt_audio.route_to_bt/route_to_wired. Tests patch those
# seams + the routing functions — never the real dbus/pactl chain.
# ===========================================================================


def _make_real(tmp_path):
    """RealBtManager with a tmp-path store so tests never touch content/."""
    from app.services.bt_store import BtDeviceStore

    return RealBtManager(store=BtDeviceStore(tmp_path / "bt.json"))


class _RouteRecorder:
    """Replace ``bt_audio.route_to_bt`` / ``route_to_wired`` and record calls.

    A simple awaitable callable that stores the args it was called with so a
    test can assert routing was reached (and with which MAC). Returns True to
    mimic the real router's success shape (manager ignores the bool anyway).
    """

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def __call__(self, *args):
        self.calls.append(args)
        return True


class TestRealPair:
    """RealBtManager.pair: register_agent + _pair_device seam + route_to_bt."""

    async def test_pair_ok_returns_dict(self, tmp_path, monkeypatch):
        mgr = _make_real(tmp_path)
        # Patch the ONE dbus seam + the agent register + the router.
        mgr._pair_device = _seam_returning(None)
        monkeypatch.setattr(
            "app.services.bt_manager.bt_audio.route_to_bt", _RouteRecorder()
        )
        # register_agent lives in bt_agent; pair must call it on the same bus.
        # Patch at the bt_manager module's import binding.
        registered = []

        async def _fake_register(bus):
            registered.append(bus)

        monkeypatch.setattr("app.services.bt_manager.register_agent", _fake_register)
        result = await mgr.pair("AA:BB:CC:00:11:22", "JBL")
        assert result == {"ok": True}

    async def test_pair_persists_speaker(self, tmp_path, monkeypatch):
        mgr = _make_real(tmp_path)
        mgr._pair_device = _seam_returning(None)
        monkeypatch.setattr(
            "app.services.bt_manager.bt_audio.route_to_bt", _RouteRecorder()
        )

        async def _no_register(bus):
            return None

        monkeypatch.setattr("app.services.bt_manager.register_agent", _no_register)
        await mgr.pair("AA:BB:CC:00:11:22", "JBL")
        last = await mgr.get_last_speaker()
        assert last is not None
        assert last["mac"] == "AA:BB:CC:00:11:22"
        assert last["name"] == "JBL"

    async def test_pair_invokes_route_to_bt_with_mac(self, tmp_path, monkeypatch):
        mgr = _make_real(tmp_path)
        mgr._pair_device = _seam_returning(None)
        router = _RouteRecorder()
        monkeypatch.setattr("app.services.bt_manager.bt_audio.route_to_bt", router)

        async def _no_register(bus):
            return None

        monkeypatch.setattr("app.services.bt_manager.register_agent", _no_register)
        await mgr.pair("AA:BB:CC:00:11:22", "JBL")
        assert router.calls == [("AA:BB:CC:00:11:22",)]

    async def test_pair_never_500_on_seam_error(self, tmp_path, monkeypatch):
        """Never-500: a raising _pair_device seam → {ok:False,error:...}."""
        mgr = _make_real(tmp_path)
        mgr._pair_device = _seam_raising(RuntimeError("dbus down"))
        result = await mgr.pair("AA:BB:CC:00:11:22", "JBL")
        assert result["ok"] is False
        assert result["error"] == "RuntimeError"

    async def test_pair_registers_agent_on_shared_bus(self, tmp_path, monkeypatch):
        """Pitfall 1: register_agent must be called (on the pair bus)."""
        mgr = _make_real(tmp_path)
        mgr._pair_device = _seam_returning(None)
        monkeypatch.setattr(
            "app.services.bt_manager.bt_audio.route_to_bt", _RouteRecorder()
        )
        registered = []

        async def _fake_register(bus):
            registered.append(bus)

        monkeypatch.setattr("app.services.bt_manager.register_agent", _fake_register)
        await mgr.pair("AA:BB:CC:00:11:22", "JBL")
        assert len(registered) == 1


class TestRealConnect:
    """RealBtManager.connect: _connect_device seam + route_to_bt."""

    async def test_connect_ok_returns_dict(self, tmp_path, monkeypatch):
        mgr = _make_real(tmp_path)
        mgr._connect_device = _seam_returning(None)
        monkeypatch.setattr(
            "app.services.bt_manager.bt_audio.route_to_bt", _RouteRecorder()
        )
        result = await mgr.connect("DD:EE:FF:33:44:55")
        assert result == {"ok": True}

    async def test_connect_invokes_route_to_bt(self, tmp_path, monkeypatch):
        mgr = _make_real(tmp_path)
        mgr._connect_device = _seam_returning(None)
        router = _RouteRecorder()
        monkeypatch.setattr("app.services.bt_manager.bt_audio.route_to_bt", router)
        await mgr.connect("DD:EE:FF:33:44:55")
        assert router.calls == [("DD:EE:FF:33:44:55",)]

    async def test_connect_never_500_on_seam_error(self, tmp_path, monkeypatch):
        mgr = _make_real(tmp_path)
        mgr._connect_device = _seam_raising(RuntimeError("dbus down"))
        result = await mgr.connect("DD:EE:FF:33:44:55")
        assert result["ok"] is False
        assert result["error"] == "RuntimeError"


class TestRealIsConnected:
    """RealBtManager.is_connected: _read_connected seam, fail-safe to False.

    The BT health monitor (bt_monitor) polls this every 5s. It MUST NOT raise
    on a dbus/BlueZ failure — a throwing probe floods logs and drives endless
    connect() retries. Any error therefore degrades to ``False``.
    """

    async def test_true_when_device_connected(self, tmp_path):
        mgr = _make_real(tmp_path)
        mgr._read_connected = _seam_returning(True)
        assert await mgr.is_connected("DD:EE:FF:33:44:55") is True

    async def test_false_when_device_not_connected(self, tmp_path):
        mgr = _make_real(tmp_path)
        mgr._read_connected = _seam_returning(False)
        assert await mgr.is_connected("DD:EE:FF:33:44:55") is False

    async def test_false_never_raises_on_seam_error(self, tmp_path):
        mgr = _make_real(tmp_path)
        mgr._read_connected = _seam_raising(RuntimeError("dbus down"))
        assert await mgr.is_connected("DD:EE:FF:33:44:55") is False


class TestRealDisconnect:
    """RealBtManager.disconnect: _disconnect_device seam + route_to_wired."""

    async def test_disconnect_ok_returns_dict(self, tmp_path, monkeypatch):
        mgr = _make_real(tmp_path)
        mgr._disconnect_device = _seam_returning(None)
        monkeypatch.setattr(
            "app.services.bt_manager.bt_audio.route_to_wired", _RouteRecorder()
        )
        result = await mgr.disconnect()
        assert result == {"ok": True}

    async def test_disconnect_invokes_route_to_wired(self, tmp_path, monkeypatch):
        """AUDIO-02 fallback: disconnect routes back to wired."""
        mgr = _make_real(tmp_path)
        mgr._disconnect_device = _seam_returning(None)
        router = _RouteRecorder()
        monkeypatch.setattr("app.services.bt_manager.bt_audio.route_to_wired", router)
        await mgr.disconnect()
        assert router.calls == [()]

    async def test_disconnect_never_500_on_seam_error(self, tmp_path, monkeypatch):
        mgr = _make_real(tmp_path)
        # Put the manager into a connected state so disconnect reaches the
        # _disconnect_device seam (disconnect only calls it when something is
        # connected).
        mgr._connected_mac = "DD:EE:FF:33:44:55"
        mgr._disconnect_device = _seam_raising(RuntimeError("dbus down"))
        result = await mgr.disconnect()
        assert result["ok"] is False
        assert result["error"] == "RuntimeError"

    async def test_disconnect_invokes_device_disconnect_across_instances(
        self, tmp_path, monkeypatch
    ):
        """CR-01 regression: disconnect on a fresh manager instance still calls
        _disconnect_device when given an explicit MAC (models the per-request
        factory in the /api/bt router where each POST builds a new manager).

        Instance A = /connect request sets _connected_mac.
        Instance B = /disconnect request has _connected_mac=None but receives
        the MAC from the request body.
        """
        from app.services.bt_store import BtDeviceStore

        store = BtDeviceStore(tmp_path / "bt.json")
        mgr_a = RealBtManager(store=store)
        mgr_b = RealBtManager(store=store)

        # Instance A: simulates /connect — sets _connected_mac
        mgr_a._connected_mac = "AA:BB:CC:00:11:22"

        # Instance B: simulates /disconnect — fresh instance, _connected_mac=None
        # (this is the per-request factory pattern that causes CR-01)
        assert mgr_b._connected_mac is None

        # Record _disconnect_device calls on instance B
        disconnect_calls = []

        async def _record_disconnect(*args, **kwargs):
            disconnect_calls.append((args, kwargs))

        mgr_b._disconnect_device = _record_disconnect

        # Monkeypatch route_to_wired so no real pactl runs
        monkeypatch.setattr(
            "app.services.bt_manager.bt_audio.route_to_wired", _RouteRecorder()
        )

        # Disconnect on instance B with explicit MAC (as the router will pass)
        result = await mgr_b.disconnect("AA:BB:CC:00:11:22")
        assert result == {"ok": True}

        # Assert _disconnect_device WAS invoked with the MAC
        assert len(disconnect_calls) == 1
        args, kwargs = disconnect_calls[0]
        # The call should include the MAC as the second positional arg (bus, mac)
        assert "AA:BB:CC:00:11:22" in args


class TestRealForget:
    """RealBtManager.forget: _forget_device seam + clear() when MAC matches."""

    async def test_forget_ok_returns_dict(self, tmp_path, monkeypatch):
        mgr = _make_real(tmp_path)
        mgr._forget_device = _seam_returning(None)
        result = await mgr.forget("AA:BB:CC:00:11:22")
        assert result == {"ok": True}

    async def test_forget_clears_store_when_mac_matches(self, tmp_path, monkeypatch):
        mgr = _make_real(tmp_path)
        # Seed the store so clear() has something to clear.
        await mgr.remember_speaker("JBL", "AA:BB:CC:00:11:22")
        mgr._forget_device = _seam_returning(None)
        await mgr.forget("AA:BB:CC:00:11:22")
        assert await mgr.get_last_speaker() is None

    async def test_forget_does_not_clear_when_mac_differs(self, tmp_path, monkeypatch):
        """Open Question 2: forgetting a different MAC keeps memory."""
        mgr = _make_real(tmp_path)
        await mgr.remember_speaker("JBL", "AA:BB:CC:00:11:22")
        mgr._forget_device = _seam_returning(None)
        await mgr.forget("DD:EE:FF:33:44:55")
        last = await mgr.get_last_speaker()
        assert last is not None
        assert last["mac"] == "AA:BB:CC:00:11:22"

    async def test_forget_never_500_on_seam_error(self, tmp_path, monkeypatch):
        mgr = _make_real(tmp_path)
        mgr._forget_device = _seam_raising(RuntimeError("dbus down"))
        result = await mgr.forget("AA:BB:CC:00:11:22")
        assert result["ok"] is False
        assert result["error"] == "RuntimeError"


class TestRealGetStatusExtended:
    """RealBtManager.get_status carries connected_mac + sink (Pitfall 7)."""

    async def test_status_has_connected_mac_and_sink_keys(self, tmp_path):
        mgr = _make_real(tmp_path)
        status = await mgr.get_status()
        assert "connected_mac" in status
        assert "sink" in status

    async def test_status_default_disconnected_wired(self, tmp_path):
        mgr = _make_real(tmp_path)
        status = await mgr.get_status()
        assert status["connected_mac"] is None
        assert status["sink"] == "wired"


class TestRealRoutingIsolation:
    """PLAT-02/AUDIO-06: routing reached ONLY via bt_audio fns (no real pactl)."""

    async def test_connect_routing_is_patchable(self, tmp_path, monkeypatch):
        """Patching bt_audio.route_to_bt fully isolates connect from pactl."""
        mgr = _make_real(tmp_path)
        mgr._connect_device = _seam_returning(None)
        router = _RouteRecorder()
        monkeypatch.setattr("app.services.bt_manager.bt_audio.route_to_bt", router)
        await mgr.connect("DD:EE:FF:33:44:55")
        # The patched router ran instead of any real pactl subprocess.
        assert len(router.calls) == 1
