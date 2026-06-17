"""Tests for the Phase 27 BT request models + extended BtStatus (BT-02/03/04, Pitfall 5/7)."""

import pytest
from pydantic import ValidationError

from app.models.bt import (
    BtConnectRequest,
    BtForgetText,
    BtPairRequest,
    BtStatus,
)

GOOD = "AA:BB:CC:00:11:22"
BAD_MACS = [
    "not-a-mac",
    "AA:BB:CC:00:11",  # 5 octets
    "AA:BB:CC:00:11:22:33",  # 7 octets
    "../etc/passwd",  # path traversal / injection attempt
    "GG:BB:CC:00:11:22",  # non-hex
]


# --- Task 1: Bt*Request models with strict MAC validation ---------------------


def test_pair_request_accepts_canonical_mac_with_name():
    req = BtPairRequest(mac=GOOD, name="JBL")
    assert req.mac == GOOD
    assert req.name == "JBL"


def test_pair_request_accepts_lowercase_mac_name_optional():
    req = BtPairRequest(mac="aa:bb:cc:00:11:22")
    assert req.mac == "aa:bb:cc:00:11:22"
    assert req.name is None


def test_connect_request_accepts_canonical_mac():
    assert BtConnectRequest(mac=GOOD).mac == GOOD


def test_forget_request_accepts_canonical_mac():
    assert BtForgetText(mac=GOOD).mac == GOOD


@pytest.mark.parametrize("bad", BAD_MACS)
def test_pair_request_rejects_malformed_mac(bad):
    with pytest.raises(ValidationError):
        BtPairRequest(mac=bad)


@pytest.mark.parametrize("bad", BAD_MACS)
def test_connect_request_rejects_malformed_mac(bad):
    with pytest.raises(ValidationError):
        BtConnectRequest(mac=bad)


@pytest.mark.parametrize("bad", BAD_MACS)
def test_forget_request_rejects_malformed_mac(bad):
    with pytest.raises(ValidationError):
        BtForgetText(mac=bad)


# --- Task 2: BtStatus extension (connected_mac + sink) -----------------------


def test_bt_status_with_connected_mac_none_and_wired_sink():
    st = BtStatus(
        name="bt",
        is_mock=True,
        status="ok",
        platform="generic",
        adapter_present=False,
        connected_mac=None,
        sink="wired",
    )
    assert st.connected_mac is None
    assert st.sink == "wired"


def test_bt_status_accepts_connected_mac_string():
    st = BtStatus(
        name="bt",
        is_mock=False,
        status="ok",
        platform="jetson",
        adapter_present=True,
        connected_mac=GOOD,
        sink="bluez_output.AA_BB_CC_00_11_22.a2dp-sink",
    )
    assert st.connected_mac == GOOD


def test_bt_status_sink_is_required():
    with pytest.raises(ValidationError):
        BtStatus(
            name="bt",
            is_mock=True,
            status="ok",
            platform="generic",
            adapter_present=False,
        )  # no sink -> must raise
