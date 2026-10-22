"""Direct-USB driver for the ACR122U, used when pcscd cannot open the reader.

After some boots the reader's firmware answers each CCID command only when the
next one arrives: replies lag a fixed number of commands behind. libccid then
times out on its first read and pcscd gives up on the reader, while the reader
itself (and its PN532 NFC chip) still works. Only a real power loss clears the
lag, and the board's USB hub cannot cut the reader's power.

This driver tolerates the lag: every command carries a sequence number, and it
sends cheap GetSlotStatus "kicks" until the reply with that sequence number
comes out. Each command releases exactly one held reply, so the lag never
shrinks or grows as long as writes are spaced out (back-to-back writes make it
grow). On a healthy reader the reply simply arrives without kicks.

Cards are detected with the PN532's InListPassiveTarget, sent as an ACR122U
pseudo-APDU over PC_to_RDR_Escape.
"""

import struct
import time

VENDOR_ID = 0x072F
PRODUCT_ID = 0x2200

EP_OUT = 0x02
EP_IN = 0x82

# CCID message types: command -> expected reply
GET_SLOT_STATUS = 0x65
ESCAPE = 0x6B
_REPLY_TYPE = {GET_SLOT_STATUS: 0x81, ESCAPE: 0x83}

WRITE_GAP_SECONDS = 0.03
READ_TIMEOUT_MS = 400
MAX_KICKS = 16

# ACR122U pseudo-APDU wrapping PN532 InListPassiveTarget: 1 target, ISO 14443A
IN_LIST_PASSIVE_TARGET = bytes([0xFF, 0x00, 0x00, 0x00, 0x04, 0xD4, 0x4A, 0x01, 0x00])
# ACR122U pseudo-APDU wrapping PN532 RFConfiguration: RF field on
RF_FIELD_ON = bytes([0xFF, 0x00, 0x00, 0x00, 0x04, 0xD4, 0x32, 0x01, 0x03])
# ACR122U LED/buzzer control: one 200 ms beep, red LED blinks once with it.
# The firmware does not beep on its own while the host drives the PN532.
BEEP = bytes([0xFF, 0x00, 0x40, 0x50, 0x04, 0x02, 0x00, 0x01, 0x01])


class ReaderError(Exception):
    """The reader is gone or stopped answering."""


def parse_uid(reply: bytes) -> str | None:
    """Return the UID from an InListPassiveTarget response, or None if no card.

    Response layout: D5 4B NbTg [Tg SENS_RES(2) SEL_RES NFCIDLength NFCID1...]
    followed by the ACR122U status word 90 00.
    """
    if len(reply) < 3 or reply[0] != 0xD5 or reply[1] != 0x4B or reply[2] < 1:
        return None
    if len(reply) < 8:
        return None
    length = reply[7]
    uid = reply[8 : 8 + length]
    if len(uid) != length or not uid:
        return None
    return ":".join(f"{b:02X}" for b in uid)


class ACR122UDirect:
    """Talk CCID to the ACR122U over pyusb, tolerating lagging replies."""

    def __init__(self, device) -> None:
        """Wrap an already-found pyusb device. Use open() to build one."""
        self._dev = device
        self._seq = 0

    @classmethod
    def open(cls) -> "ACR122UDirect":
        """Find and claim the reader. Raises ReaderError if absent or busy."""
        try:
            import usb.core
            import usb.util

            dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
            if dev is None:
                raise ReaderError("ACR122U not on the USB bus")
            usb.util.claim_interface(dev, 0)
        except ReaderError:
            raise
        except Exception as exc:  # busy (pcscd holds it), permissions, no libusb
            raise ReaderError(f"cannot claim ACR122U: {exc}") from exc
        reader = cls(dev)
        reader.command(ESCAPE, RF_FIELD_ON)
        return reader

    def close(self) -> None:
        """Release the reader; safe to call more than once."""
        if self._dev is None:
            return
        try:
            import usb.util

            usb.util.release_interface(self._dev, 0)
            usb.util.dispose_resources(self._dev)
        except Exception:
            pass
        self._dev = None

    def _write(self, msg_type: int, payload: bytes = b"") -> int:
        self._seq = (self._seq + 1) & 0xFF
        header = struct.pack("<BIBB3x", msg_type, len(payload), 0, self._seq)
        time.sleep(WRITE_GAP_SECONDS)  # back-to-back writes grow the lag
        try:
            self._dev.write(EP_OUT, header + payload, timeout=1000)
        except Exception as exc:
            raise ReaderError(f"write failed: {exc}") from exc
        return self._seq

    def _read(self) -> bytes | None:
        import usb.core

        try:
            return bytes(self._dev.read(EP_IN, 271, timeout=READ_TIMEOUT_MS))
        except usb.core.USBTimeoutError:
            return None
        except Exception as exc:
            raise ReaderError(f"read failed: {exc}") from exc

    def command(self, msg_type: int, payload: bytes = b"") -> bytes:
        """Send one CCID command and return its reply's data field."""
        seq = self._write(msg_type, payload)
        expected = _REPLY_TYPE[msg_type]
        for _ in range(MAX_KICKS):
            reply = self._read()
            if reply is not None and reply[0] == expected and reply[6] == seq:
                return reply[10:]
            # Not ours (held back, or a stale reply): release the next one.
            self._write(GET_SLOT_STATUS)
        raise ReaderError("no reply from ACR122U")

    def read_uid(self) -> str | None:
        """Scan once for a card and return its UID, or None."""
        return parse_uid(self.command(ESCAPE, IN_LIST_PASSIVE_TARGET))

    def beep(self) -> None:
        """Sound the reader's buzzer once (tap feedback for the child)."""
        self.command(ESCAPE, BEEP)
