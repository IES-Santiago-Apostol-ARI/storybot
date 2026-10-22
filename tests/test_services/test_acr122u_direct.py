"""Tests for the lag-tolerant ACR122U direct-USB driver."""

import struct
from collections import deque

import pytest
import usb.core

from app.services import acr122u_direct
from app.services.acr122u_direct import (
    ESCAPE,
    GET_SLOT_STATUS,
    ACR122UDirect,
    ReaderError,
    parse_uid,
)

# D5 4B NbTg=1 Tg=1 SENS_RES=0044 SEL_RES=00 len=7 UID SW=9000
CARD_REPLY = bytes.fromhex("d54b0101004400" "07" "047ea40ecc2a81" "9000")
UID = "04:7E:A4:0E:CC:2A:81"
NO_CARD_REPLY = bytes.fromhex("d54b009000")


class LaggingReader:
    """Fake ACR122U whose replies come out `lag` commands late, like the
    stuck firmware: each OUT transfer releases exactly one held reply."""

    def __init__(self, lag: int, card: bool = True, stale: list[bytes] = ()) -> None:
        self.lag = lag
        self.card = card
        self.held: deque[bytes] = deque(stale)
        self.out: deque[bytes] = deque()
        self.writes = 0

    def _reply(self, msg: bytes) -> bytes:
        msg_type, seq = msg[0], msg[6]
        if msg_type == GET_SLOT_STATUS:
            return bytes([0x81, 0, 0, 0, 0, 0, seq, 0x02, 0x81, 0x00])
        data = b"\x90\x00"
        if msg[15:17] == b"\xd4\x4a":  # InListPassiveTarget
            data = CARD_REPLY if self.card else NO_CARD_REPLY
        return (
            bytes([0x83])
            + struct.pack("<I", len(data))
            + bytes([0, seq, 0, 0, 0])
            + data
        )

    def write(self, ep, data, timeout=None):
        self.writes += 1
        self.held.append(self._reply(bytes(data)))
        if len(self.held) > self.lag:
            self.out.append(self.held.popleft())

    def read(self, ep, size, timeout=None):
        if not self.out:
            raise usb.core.USBTimeoutError("timeout")
        return self.out.popleft()


@pytest.fixture(autouse=True)
def no_write_gap(monkeypatch):
    monkeypatch.setattr(acr122u_direct, "WRITE_GAP_SECONDS", 0)


class TestParseUid:
    def test_card(self):
        assert parse_uid(CARD_REPLY) == UID

    def test_no_card(self):
        assert parse_uid(NO_CARD_REPLY) is None

    def test_garbage(self):
        assert parse_uid(b"\x90\x00") is None
        assert parse_uid(b"") is None


class TestLagTolerance:
    @pytest.mark.parametrize("lag", [0, 1, 3])
    def test_reads_uid_at_any_lag(self, lag):
        reader = ACR122UDirect(LaggingReader(lag))
        assert reader.read_uid() == UID
        assert reader.read_uid() == UID  # lag stays stable

    def test_no_card(self):
        reader = ACR122UDirect(LaggingReader(1, card=False))
        assert reader.read_uid() is None

    def test_healthy_reader_needs_no_kicks(self):
        dev = LaggingReader(0)
        ACR122UDirect(dev).read_uid()
        assert dev.writes == 1

    def test_stale_reply_with_same_seq_is_not_taken(self):
        """A leftover GetSlotStatus reply from pcscd carrying the seq our first
        command will use must not be mistaken for that command's reply."""
        stale = bytes([0x81, 0, 0, 0, 0, 0, 1, 0x02, 0x81, 0x00])
        reader = ACR122UDirect(LaggingReader(1, stale=[stale]))
        assert reader.read_uid() == UID

    def test_silent_reader_raises(self):
        class Silent(LaggingReader):
            def write(self, ep, data, timeout=None):
                pass

        with pytest.raises(ReaderError):
            ACR122UDirect(Silent(0)).command(ESCAPE, b"")
