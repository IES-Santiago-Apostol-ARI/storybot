"""Tests for app.models.bt + app.services.bt_store (Plan 26-01, Task 1).

Covers:
- BtDevice / BtStatus / LastSpeaker pydantic models
- BtDeviceStore: round-trip save→load, missing-file → None,
  corrupt-file → None, atomic write (os.replace) present.
"""

import json
from pathlib import Path

import pytest

from app.models.bt import BtDevice, BtStatus, LastSpeaker
from app.services.bt_store import BtDeviceStore


# ---------------------------------------------------------------------------
# BtDevice model
# ---------------------------------------------------------------------------


class TestBtDeviceModel:
    """BtDevice model validation."""

    def test_valid_with_negative_rssi(self):
        dev = BtDevice(name="Aula JBL", mac="00:42:79:E9:90:46", rssi=-45)
        assert dev.name == "Aula JBL"
        assert dev.mac == "00:42:79:E9:90:46"
        assert dev.rssi == -45

    def test_rssi_defaults_none(self):
        dev = BtDevice(name="X", mac="AA:BB:CC:DD:EE:FF")
        assert dev.rssi is None

    def test_rssi_none_explicit(self):
        dev = BtDevice(name="X", mac="AA:BB:CC:DD:EE:FF", rssi=None)
        assert dev.rssi is None

    def test_missing_name_rejected(self):
        with pytest.raises(Exception):
            BtDevice(mac="AA:BB:CC:DD:EE:FF")

    def test_missing_mac_rejected(self):
        with pytest.raises(Exception):
            BtDevice(name="X")


class TestBtStatusModel:
    """BtStatus model validation."""

    def test_valid_construction(self):
        st = BtStatus(
            name="bt",
            is_mock=True,
            status="ok",
            platform="generic",
            adapter_present=False,
            sink="wired",
        )
        assert st.is_mock is True
        assert st.error_message is None

    def test_error_message_optional(self):
        st = BtStatus(
            name="bt",
            is_mock=False,
            status="unavailable",
            platform="generic",
            adapter_present=True,
            error_message="no adapter",
            sink="wired",
        )
        assert st.error_message == "no adapter"


class TestLastSpeakerModel:
    """LastSpeaker model validation."""

    def test_valid_construction(self):
        ls = LastSpeaker(
            name="Aula JBL",
            mac="00:42:79:E9:90:46",
            last_connected="2026-06-12T17:00:00+00:00",
        )
        assert ls.name == "Aula JBL"
        assert ls.mac == "00:42:79:E9:90:46"


# ---------------------------------------------------------------------------
# BtDeviceStore persistence
# ---------------------------------------------------------------------------


class TestBtDeviceStore:
    """BtDeviceStore single-speaker JSON persistence."""

    def test_round_trip_returns_name_mac_and_iso_timestamp(self, tmp_path):
        store = BtDeviceStore(path=tmp_path / "bt_devices.json")
        store.save_last_speaker("Aula JBL", "00:42:79:E9:90:46")
        result = store.get_last_speaker()
        assert result is not None
        assert result["name"] == "Aula JBL"
        assert result["mac"] == "00:42:79:E9:90:46"
        # last_connected is an ISO-8601 string
        assert isinstance(result["last_connected"], str)
        assert "T" in result["last_connected"]

    def test_missing_file_returns_none(self, tmp_path):
        store = BtDeviceStore(path=tmp_path / "does_not_exist.json")
        assert store.get_last_speaker() is None

    def test_corrupt_file_returns_none(self, tmp_path):
        path = tmp_path / "bt_devices.json"
        path.write_text("this is { not valid json")
        store = BtDeviceStore(path=path)
        assert store.get_last_speaker() is None

    def test_non_dict_file_returns_none(self, tmp_path):
        # json.loads of a list → .get raises AttributeError/TypeError → None
        path = tmp_path / "bt_devices.json"
        path.write_text("[1, 2, 3]")
        store = BtDeviceStore(path=path)
        assert store.get_last_speaker() is None

    def test_save_uses_atomic_replace(self, tmp_path):
        path = tmp_path / "bt_devices.json"
        store = BtDeviceStore(path=path)
        store.save_last_speaker("Mock JBL", "AA:BB:CC:00:11:22")
        # Final file is valid JSON shaped {"last_speaker": {...}}
        data = json.loads(path.read_text())
        assert "last_speaker" in data
        assert data["last_speaker"]["name"] == "Mock JBL"
        # No leftover temp file
        assert not (tmp_path / "bt_devices.json.tmp").exists()

    def test_save_creates_parent_dir(self, tmp_path):
        nested = tmp_path / "nested" / "sub" / "bt_devices.json"
        store = BtDeviceStore(path=nested)
        store.save_last_speaker("X", "AA:BB:CC:DD:EE:FF")
        assert nested.exists()

    def test_save_overwrites_previous_single_speaker(self, tmp_path):
        """D-01: persist exactly ONE last_speaker (not a list)."""
        store = BtDeviceStore(path=tmp_path / "bt_devices.json")
        store.save_last_speaker("First", "AA:BB:CC:DD:EE:FF")
        store.save_last_speaker("Second", "11:22:33:44:55:66")
        result = store.get_last_speaker()
        assert result is not None
        assert result["name"] == "Second"
        assert result["mac"] == "11:22:33:44:55:66"
        # Single-speaker shape: exactly one last_speaker key
        data = json.loads((tmp_path / "bt_devices.json").read_text())
        assert list(data.keys()) == ["last_speaker"]

    def test_default_path_resolves_to_content_bt_devices_json(self):
        """Default path mirrors ConfigManager: project_root/content/bt_devices.json."""
        store = BtDeviceStore()
        expected = Path(__file__).resolve().parent.parent.parent / "content" / "bt_devices.json"
        assert store.path == expected

    def test_source_uses_os_replace(self):
        """Atomic write must use os.replace (D-03, threat T-26-03)."""
        src = Path("app/services/bt_store.py").read_text()
        assert "os.replace" in src
