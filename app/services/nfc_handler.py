"""NFC reader service with real and mock implementations."""

import threading
import time
from collections.abc import Callable

from app.services.base import HardwareService


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
    """Real NFC service using nfcpy."""

    def __init__(self) -> None:
        """Initialize real NFC service."""
        self._polling = False
        self._poll_thread: threading.Thread | None = None
        self._callbacks: list[Callable[[str], None]] = []
        self._lock = threading.Lock()
        self._available = self._check_availability()

    @property
    def is_mock(self) -> bool:
        """Return False - this is real NFC service."""
        return False

    def _check_availability(self) -> bool:
        """Check if NFC hardware is available."""
        try:
            import nfc

            return True
        except (ImportError, OSError):
            return False

    async def start_polling(self, callback: Callable[[str], None]) -> None:
        """Register callback and start polling thread if not already running."""
        if not self._available:
            raise RuntimeError("NFC hardware not available")

        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)

            thread_dead = self._poll_thread is None or not self._poll_thread.is_alive()
            if not self._polling or thread_dead:
                self._polling = True
                self._poll_thread = threading.Thread(
                    target=self._poll_loop, daemon=True, name="NFCPoller"
                )
                self._poll_thread.start()

    def _reset_usb_device(self) -> None:
        """Reset USB device to clear bad state from unclean shutdown."""
        try:
            import usb.core
            import usb.util

            dev = usb.core.find(idVendor=0x072F, idProduct=0x2200)
            if dev:
                dev.reset()
                usb.util.dispose_resources(dev)
                time.sleep(1.5)
        except Exception:
            pass

    def _poll_loop(self) -> None:
        """Background thread polling loop. Retries on device open failure."""
        import nfc

        # Reset the USB device before the first open attempt. The ACR122U
        # retains state across reboots (stays bus-powered), so a software reset
        # here is equivalent to the manual unplug/replug workaround.
        self._reset_usb_device()

        last_uid: str | None = None
        last_uid_time: float = 0.0
        DEBOUNCE_SECONDS = 2.0

        def on_connect(tag) -> bool:
            nonlocal last_uid, last_uid_time
            if hasattr(tag, "identifier"):
                uid = ":".join([f"{b:02X}" for b in tag.identifier])
                now = time.monotonic()
                if uid == last_uid and (now - last_uid_time) < DEBOUNCE_SECONDS:
                    return False  # Same card still in range, suppress
                last_uid = uid
                last_uid_time = now
                with self._lock:
                    callbacks = list(self._callbacks)
                for cb in callbacks:
                    cb(uid)
            return False  # Don't stay connected; resume polling immediately

        while self._polling:
            try:
                clf = nfc.ContactlessFrontend("usb")
            except OSError as e:
                import errno as errno_mod
                if e.errno == errno_mod.EIO:
                    # Device in bad state (e.g. unclean shutdown) — reset and retry
                    self._reset_usb_device()
                else:
                    # Device not ready yet (boot timing) — wait and retry
                    time.sleep(2.0)
                continue
            except Exception:
                time.sleep(2.0)
                continue

            try:
                while self._polling:
                    clf.connect(
                        rdwr={"on-connect": on_connect},
                        terminate=lambda: not self._polling,
                    )
            except Exception:
                pass
            finally:
                try:
                    clf.close()
                except Exception:
                    pass

            if self._polling:
                # Brief pause before reopening device (e.g. after USB disconnect)
                time.sleep(1.0)

    async def stop_polling(self, callback: Callable[[str], None] | None = None) -> None:
        """Unregister callback. Thread keeps running until shutdown() is called."""
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
                "error_message": "NFC hardware not available",
            }

        status_val = "ok" if self._polling else "idle"
        return {
            "name": "nfc",
            "is_mock": self.is_mock,
            "status": status_val,
            "error_message": None,
        }

    async def initialize(self) -> None:
        """Initialize NFC service and start poll thread."""
        self._available = self._check_availability()
        if self._available:
            self._polling = True
            self._poll_thread = threading.Thread(
                target=self._poll_loop, daemon=True, name="NFCPoller"
            )
            self._poll_thread.start()

    async def shutdown(self) -> None:
        """Shutdown NFC service - stop polling thread."""
        with self._lock:
            self._callbacks.clear()
            self._polling = False
        if self._poll_thread:
            self._poll_thread.join(timeout=5.0)
            self._poll_thread = None


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
        RealNFCService if NFC hardware available, else MockNFCService.
    """
    # Try real first
    real_service = RealNFCService()
    if real_service._available:
        return real_service
    return MockNFCService()
