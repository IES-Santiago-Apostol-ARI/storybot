"""NFC reader service using pyscard (PC/SC) with real and mock implementations.

The ACR122U is a CCID-compliant reader — pyscard via pcscd is the correct
stack for it on Linux. nfcpy's own docs warn against ACR122U because the
USB-CCID layer prevents full direct access to the PN532 chip.

pcscd manages the device lifecycle at the daemon level, so the firmware hang
that affected nfcpy (red LED, beeping after close) does not occur here.
"""

import threading
import time
from collections.abc import Callable

from app.services.base import HardwareService

DEBOUNCE_SECONDS = 0.4
RETRY_INTERVAL_SECONDS = 5.0


class NFCService(HardwareService):
    """Protocol for NFC service."""

    @property
    def is_mock(self) -> bool:
        """Return True if this is a mock service."""
        ...

    async def start_polling(self, callback: Callable[[str], None]) -> None:
        """Start polling for NFC cards.

        Args:
            callback: Function to call when card tapped, receives UID as string.
        """
        ...

    async def stop_polling(self) -> None:
        """Stop polling for NFC cards."""
        ...

    @property
    def is_polling(self) -> bool:
        """Check if currently polling."""
        ...


class RealNFCService(NFCService):
    """Real NFC service using pyscard + pcscd."""

    def __init__(self) -> None:
        """Initialize real NFC service."""
        self._polling = False
        self._callbacks: list[Callable[[str], None]] = []
        self._lock = threading.Lock()
        self._monitor = None
        self._observer = None
        self._last_uid_time: dict[str, float] = {}
        self._available = self._check_availability()
        self._shutdown_event = threading.Event()
        self._retry_thread: threading.Thread | None = None

    @property
    def is_mock(self) -> bool:
        """Return False - this is real NFC service."""
        return False

    def _check_availability(self) -> bool:
        """Check if pyscard is importable and pcscd has at least one reader."""
        try:
            from smartcard.System import readers

            return bool(readers())
        except Exception:
            return False

    def _get_uid(self, card) -> str | None:
        """Connect to card and read UID via APDU FF CA 00 00 00.

        card.reader is the reader name string in pyscard; look up the actual
        reader object from readers() to create a connection.
        """
        try:
            from smartcard.System import readers

            reader_name = str(card.reader)
            matching = [r for r in readers() if str(r) == reader_name]
            if not matching:
                return None
            conn = matching[0].createConnection()
            conn.connect()
            data, sw1, sw2 = conn.transmit([0xFF, 0xCA, 0x00, 0x00, 0x00])
            conn.disconnect()
            if (sw1, sw2) == (0x90, 0x00) and data:
                return ":".join(f"{b:02X}" for b in data)
        except Exception:
            pass
        return None

    def _make_observer(self):
        """Create a CardObserver that fires our callbacks on card insertion."""
        import logging

        from smartcard.CardMonitoring import CardObserver

        logger = logging.getLogger(__name__)
        service = self

        class _Observer(CardObserver):
            def update(self, observable, handlers):
                addedcards, _ = handlers
                for card in addedcards:
                    uid = service._get_uid(card)
                    if uid:
                        now = time.monotonic()
                        elapsed = now - service._last_uid_time.get(uid, 0.0)
                        if elapsed < DEBOUNCE_SECONDS:
                            logger.debug("NFC debounced: %s", uid)
                            continue
                        service._last_uid_time[uid] = now
                        logger.info("NFC card detected: %s", uid)
                        with service._lock:
                            callbacks = list(service._callbacks)
                        for cb in callbacks:
                            cb(uid)

        return _Observer()

    def _start_monitor(self) -> None:
        """Start CardMonitor background thread."""
        from smartcard.CardMonitoring import CardMonitor

        self._observer = self._make_observer()
        self._monitor = CardMonitor()
        self._monitor.addObserver(self._observer)
        self._polling = True

    def _retry_loop(self) -> None:
        """Background thread: re-check availability until reader found or shutdown."""
        import logging

        logger = logging.getLogger(__name__)
        while not self._shutdown_event.wait(RETRY_INTERVAL_SECONDS):
            if self._check_availability():
                logger.info("NFC reader detected after replug — starting monitor")
                self._available = True
                if not self._polling:
                    self._start_monitor()
                break

    async def start_polling(self, callback: Callable[[str], None]) -> None:
        """Register callback.

        Starts monitor if available; defers until reader appears.
        """
        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)
        if self._available and not self._polling:
            self._start_monitor()

    async def stop_polling(self, callback: Callable[[str], None] | None = None) -> None:
        """Unregister callback. Monitor keeps running until shutdown()."""
        with self._lock:
            if callback is not None and callback in self._callbacks:
                self._callbacks.remove(callback)

    @property
    def is_polling(self) -> bool:
        """Check if currently polling."""
        return self._polling

    async def get_status(self) -> dict:
        """Get NFC service status."""
        if not self._available:
            return {
                "name": "nfc",
                "is_mock": self.is_mock,
                "status": "not_connected",
                "error_message": (
                    "NFC reader not detected. After reboot, unplug and replug"
                    " the ACR122U — the app will recover automatically."
                ),
            }
        status_val = "ok" if self._polling else "idle"
        return {
            "name": "nfc",
            "is_mock": self.is_mock,
            "status": status_val,
            "error_message": None,
        }

    async def initialize(self) -> None:
        """Initialize NFC service and start CardMonitor."""
        import logging

        self._available = self._check_availability()
        if self._available:
            self._start_monitor()
        else:
            logging.getLogger(__name__).warning(
                "NFC reader not available at startup — retrying every %.0fs. "
                "After reboot, unplug and replug the ACR122U.",
                RETRY_INTERVAL_SECONDS,
            )
            self._retry_thread = threading.Thread(
                target=self._retry_loop, daemon=True, name="nfc-retry"
            )
            self._retry_thread.start()

    async def shutdown(self) -> None:
        """Shutdown NFC service — stop CardMonitor."""
        self._shutdown_event.set()
        self._polling = False
        with self._lock:
            self._callbacks.clear()
        if self._monitor is not None and self._observer is not None:
            try:
                self._monitor.deleteObserver(self._observer)
            except Exception:
                pass
        self._monitor = None
        self._observer = None


class MockNFCService(NFCService):
    """Mock NFC service for testing without hardware."""

    def __init__(self) -> None:
        """Initialize mock NFC service."""
        self._polling = False
        self._callback: Callable[[str], None] | None = None

    @property
    def is_mock(self) -> bool:
        """Return True - this is mock NFC service."""
        return True

    async def start_polling(self, callback: Callable[[str], None]) -> None:
        """Start mock polling (just stores callback)."""
        self._callback = callback
        self._polling = True

    async def stop_polling(self) -> None:
        """Stop mock polling."""
        self._polling = False
        self._callback = None

    @property
    def is_polling(self) -> bool:
        """Check if mock polling."""
        return self._polling

    def simulate_tap(self, uid: str) -> None:
        """Simulate a card tap (for testing).

        Args:
            uid: Card UID as hex string (e.g., "04:A3:5B:C2:D4:30").
        """
        if self._callback:
            self._callback(uid)

    async def get_status(self) -> dict:
        """Get mock NFC service status."""
        return {
            "name": "nfc",
            "is_mock": self.is_mock,
            "status": "ok",
            "error_message": None,
        }

    async def initialize(self) -> None:
        """Initialize mock NFC service."""
        self._polling = False

    async def shutdown(self) -> None:
        """Shutdown mock NFC service."""
        await self.stop_polling()


def create_nfc_service() -> NFCService:
    """Create appropriate NFC service based on hardware availability.

    Returns:
        RealNFCService if pyscard is installed (handles reader unavailability
        with auto-retry), else MockNFCService when pyscard is absent entirely.
    """
    try:
        import smartcard  # noqa: F401

        return RealNFCService()
    except ImportError:
        return MockNFCService()
