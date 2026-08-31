"""Tests for NFC handler service."""

import asyncio
import sys
import threading
from unittest import mock

import pytest

from app.services.nfc_handler import (
    MockNFCService,
    RealNFCService,
    create_nfc_service,
)


def nfc_available() -> bool:
    """Check if NFC hardware is available (pyscard + pcscd running)."""
    try:
        from smartcard.System import readers

        return bool(readers())
    except Exception:
        return False


skip_if_no_nfc = pytest.mark.skipif(
    not nfc_available(), reason="pcscd not running or no NFC reader detected"
)


@pytest.fixture
def mock_nfc_service():
    """Create a mock NFC service for testing."""
    return MockNFCService()


@pytest.fixture
def real_nfc_service():
    """Create a real NFC service for testing."""
    return RealNFCService()


class TestMockNFCService:
    """Test mock NFC service functionality."""

    @pytest.mark.asyncio
    async def test_mock_nfc_service_initializes(self, mock_nfc_service):
        """Test that mock NFC service can be created."""
        assert mock_nfc_service is not None
        assert hasattr(mock_nfc_service, "is_mock")
        assert hasattr(mock_nfc_service, "start_polling")
        assert hasattr(mock_nfc_service, "stop_polling")
        assert hasattr(mock_nfc_service, "simulate_tap")

    @pytest.mark.asyncio
    async def test_mock_nfc_service_is_mock(self, mock_nfc_service):
        """Test that mock NFC service reports as mock."""
        assert mock_nfc_service.is_mock is True

    @pytest.mark.asyncio
    async def test_mock_nfc_service_polling(self, mock_nfc_service):
        """Test polling lifecycle."""
        uid_received = []

        def callback(uid: str):
            uid_received.append(uid)

        await mock_nfc_service.start_polling(callback)
        # Mock doesn't actually poll, just sets up callback
        await mock_nfc_service.stop_polling()

    @pytest.mark.asyncio
    async def test_mock_nfc_service_simulate_tap(self, mock_nfc_service):
        """Test simulating a card tap."""
        uid_received = []

        def callback(uid: str):
            uid_received.append(uid)

        test_uid = "04:A3:5B:C2:D4:30"
        await mock_nfc_service.start_polling(callback)
        mock_nfc_service.simulate_tap(test_uid)

        # Give callback time to execute
        await asyncio.sleep(0.1)

        assert test_uid in uid_received
        await mock_nfc_service.stop_polling()

    @pytest.mark.asyncio
    async def test_mock_nfc_service_get_status(self, mock_nfc_service):
        """Test getting mock NFC service status."""
        status = await mock_nfc_service.get_status()
        assert "name" in status
        assert "is_mock" in status
        assert "status" in status
        assert status["name"] == "nfc"
        assert status["is_mock"] is True

    @pytest.mark.asyncio
    async def test_mock_nfc_service_initialize_and_shutdown(self, mock_nfc_service):
        """Test initialize and shutdown methods."""
        await mock_nfc_service.initialize()
        await mock_nfc_service.shutdown()
        assert not mock_nfc_service.is_polling

    @pytest.mark.asyncio
    async def test_mock_nfc_service_simulate_tap_without_callback(
        self, mock_nfc_service
    ):
        """Test simulate_tap does nothing without callback."""
        # Should not raise
        mock_nfc_service.simulate_tap("AA:BB:CC:DD")

    @pytest.mark.asyncio
    async def test_mock_nfc_service_is_polling_property(self, mock_nfc_service):
        """Test is_polling property changes with polling state."""
        assert mock_nfc_service.is_polling is False

        await mock_nfc_service.start_polling(lambda uid: None)
        assert mock_nfc_service.is_polling is True

        await mock_nfc_service.stop_polling()
        assert mock_nfc_service.is_polling is False

    @pytest.mark.asyncio
    async def test_mock_stop_polling_accepts_callback_like_real(self, mock_nfc_service):
        """IMPROVEMENTS.md 1.3: /api/nfc/read's finally calls
        stop_polling(card_callback); the mock must accept the same signature
        as RealNFCService or every SSE disconnect raises TypeError on devices
        where pyscard is unavailable (Arduino UNO Q)."""

        def cb(uid: str) -> None:
            pass

        await mock_nfc_service.start_polling(cb)
        await mock_nfc_service.stop_polling(cb)  # must not raise
        assert mock_nfc_service.is_polling is False

    @pytest.mark.asyncio
    async def test_mock_supports_multiple_subscribers(self, mock_nfc_service):
        """Kiosk + admin can be connected at once: a tap must reach every
        registered callback, and unregistering one must keep the others
        (mirrors RealNFCService's callback list)."""
        seen1: list[str] = []
        seen2: list[str] = []

        def cb1(uid: str) -> None:
            seen1.append(uid)

        def cb2(uid: str) -> None:
            seen2.append(uid)

        await mock_nfc_service.start_polling(cb1)
        await mock_nfc_service.start_polling(cb2)
        mock_nfc_service.simulate_tap("AA:BB:CC:01")
        assert seen1 == ["AA:BB:CC:01"]
        assert seen2 == ["AA:BB:CC:01"]

        await mock_nfc_service.stop_polling(cb1)
        mock_nfc_service.simulate_tap("AA:BB:CC:02")
        assert seen1 == ["AA:BB:CC:01"]  # unregistered — no second tap
        assert seen2 == ["AA:BB:CC:01", "AA:BB:CC:02"]
        assert mock_nfc_service.is_polling is True  # cb2 still registered


class TestRealNFCService:
    """Test real NFC service functionality."""

    @pytest.mark.asyncio
    async def test_real_nfc_service_initializes(self, real_nfc_service):
        """Test that real NFC service can be created."""
        assert real_nfc_service is not None
        assert hasattr(real_nfc_service, "is_mock")
        assert hasattr(real_nfc_service, "start_polling")
        assert hasattr(real_nfc_service, "stop_polling")

    @pytest.mark.asyncio
    async def test_real_nfc_service_is_not_mock(self, real_nfc_service):
        """Test that real NFC service reports as not mock."""
        assert real_nfc_service.is_mock is False

    @pytest.mark.asyncio
    async def test_real_nfc_service_not_polling_initially(self, real_nfc_service):
        """Test that service is not polling initially."""
        assert real_nfc_service.is_polling is False

    @pytest.mark.asyncio
    async def test_real_nfc_service_get_status_not_available(self, real_nfc_service):
        """Test get_status when hardware not available."""
        # Force _available to False to test this code path
        real_nfc_service._available = False
        status = await real_nfc_service.get_status()
        assert status["name"] == "nfc"
        assert status["is_mock"] is False
        assert status["status"] == "not_connected"
        assert "not detected" in status["error_message"]

    @pytest.mark.asyncio
    async def test_real_nfc_service_get_status_available_idle(self, real_nfc_service):
        """Test get_status when available but not polling."""
        real_nfc_service._available = True
        status = await real_nfc_service.get_status()
        assert status["status"] == "idle"
        assert status["error_message"] is None

    @pytest.mark.asyncio
    async def test_real_nfc_service_get_status_available_polling(
        self, real_nfc_service
    ):
        """Test get_status when available and polling."""
        real_nfc_service._available = True
        real_nfc_service._polling = True
        status = await real_nfc_service.get_status()
        assert status["status"] == "ok"

    @pytest.mark.asyncio
    async def test_real_nfc_service_start_polling_without_hardware(
        self, real_nfc_service
    ):
        """Test start_polling registers callback silently without hardware."""
        # Force _available to False to test this code path
        real_nfc_service._available = False

        def callback(uid: str) -> None:
            pass

        await real_nfc_service.start_polling(callback)
        assert callback in real_nfc_service._callbacks

    @pytest.mark.asyncio
    async def test_real_nfc_service_start_polling_already_polling(
        self, real_nfc_service
    ):
        """Test start_polling returns early if already polling."""
        real_nfc_service._available = True
        real_nfc_service._polling = True

        # Should return without starting new thread
        await real_nfc_service.start_polling(lambda uid: None)
        assert real_nfc_service._polling is True

    @pytest.mark.asyncio
    async def test_real_nfc_service_stop_polling(self, real_nfc_service):
        """Test stop_polling removes the callback from the list."""

        def cb(uid: str) -> None:
            pass

        real_nfc_service._callbacks = [cb]
        await real_nfc_service.stop_polling(cb)
        assert cb not in real_nfc_service._callbacks

    @pytest.mark.asyncio
    async def test_real_nfc_service_initialize(self, real_nfc_service):
        """Test initialize method."""
        await real_nfc_service.initialize()
        # Just verifies it runs without error

    @pytest.mark.asyncio
    async def test_real_nfc_service_shutdown(self, real_nfc_service):
        """Test shutdown method stops polling."""
        real_nfc_service._polling = True
        await real_nfc_service.shutdown()
        assert real_nfc_service._polling is False

    @pytest.mark.asyncio
    async def test_real_nfc_service_stop_polling_with_thread(self, real_nfc_service):
        """Test stop_polling removes only the specified callback, preserving others."""

        def cb1(uid: str) -> None:
            pass

        def cb2(uid: str) -> None:
            pass

        real_nfc_service._callbacks = [cb1, cb2]

        await real_nfc_service.stop_polling(cb1)

        assert cb1 not in real_nfc_service._callbacks
        assert cb2 in real_nfc_service._callbacks

    @pytest.mark.asyncio
    @skip_if_no_nfc
    async def test_real_nfc_service_start_polling_creates_thread(
        self, real_nfc_service
    ):
        """Test start_polling registers callback and starts CardMonitor."""
        assert real_nfc_service._available is True

        callback_called = []

        def test_callback(uid: str):
            callback_called.append(uid)

        # Start polling - registers callback and starts CardMonitor
        await real_nfc_service.start_polling(test_callback)

        # Verify callback registered and monitor started
        assert real_nfc_service._polling is True
        assert test_callback in real_nfc_service._callbacks

        # Clean up - shutdown stops the CardMonitor
        await real_nfc_service.shutdown()
        assert real_nfc_service._polling is False

    @pytest.mark.asyncio
    @skip_if_no_nfc
    async def test_real_nfc_service_check_availability_with_nfc(self, real_nfc_service):
        """Test _check_availability returns True when pyscard + pcscd available."""
        result = real_nfc_service._check_availability()
        assert result is True

    @pytest.mark.asyncio
    async def test_real_nfc_service_check_availability_without_nfc(self, monkeypatch):
        """Test _check_availability returns False when smartcard import fails."""
        # Setting the module entries to None makes `from smartcard.System import
        # readers` raise ImportError — popping them instead just triggers a fresh
        # re-import from disk, which succeeds when pyscard is installed (as it is
        # on this Jetson), so the "no nfc" path was never actually exercised.
        monkeypatch.setitem(sys.modules, "smartcard", None)
        monkeypatch.setitem(sys.modules, "smartcard.System", None)
        service = RealNFCService()
        assert service._available is False


class TestCreateNFCService:
    """Test NFC service factory function."""

    def test_create_nfc_service_returns_real_with_nfc_installed(self):
        """Test that create_nfc_service returns RealNFCService when nfc installed."""
        service = create_nfc_service()
        # pyscard is installed, so should return RealNFCService
        assert isinstance(service, RealNFCService)
        assert service.is_mock is False

    def test_create_nfc_service_returns_service_with_correct_type(self):
        """Test that create_nfc_service returns a valid NFC service."""
        service = create_nfc_service()
        # Should have required methods regardless of type
        assert hasattr(service, "start_polling")
        assert hasattr(service, "stop_polling")
        assert hasattr(service, "is_polling")
        assert hasattr(service, "get_status")


class TestMonitorStartRace:
    """Tarea 4: the nfc-retry thread and the event loop must never start the
    CardMonitor twice — two addObserver calls on the singleton mean every tap
    fires the callbacks twice and one observer leaks past shutdown()."""

    @staticmethod
    def _make_service() -> RealNFCService:
        service = RealNFCService()
        service._available = True
        return service

    def test_monitor_started_once_under_race(self):
        """Two callers racing at the barrier: exactly one addObserver."""
        import smartcard.CardMonitoring as card_monitoring  # noqa: N813

        for _ in range(20):
            calls: list = []
            calls_lock = threading.Lock()
            errors: list = []

            class CountingCardMonitor:
                def addObserver(self, observer):  # noqa: N802
                    with calls_lock:
                        calls.append(observer)

                def deleteObserver(self, observer):  # noqa: N802
                    pass

            service = self._make_service()
            barrier = threading.Barrier(2)

            def retry_path():
                try:
                    barrier.wait()
                    if service._claim_monitor_start():
                        service._start_monitor()
                except Exception as e:  # a dying thread would hide the race
                    errors.append(e)

            def polling_path():
                try:
                    barrier.wait()
                    asyncio.run(service.start_polling(lambda uid: None))
                except Exception as e:
                    errors.append(e)

            with mock.patch.object(card_monitoring, "CardMonitor", CountingCardMonitor):
                threads = [
                    threading.Thread(target=retry_path),
                    threading.Thread(target=polling_path),
                ]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()

            assert not errors
            assert len(calls) == 1

    def test_no_monitor_start_after_shutdown(self):
        """shutdown() sets the event; the retry-loop body must not start."""
        import smartcard.CardMonitoring as card_monitoring  # noqa: N813

        calls: list = []

        class CountingCardMonitor:
            def addObserver(self, observer):  # noqa: N802
                calls.append(observer)

        service = self._make_service()
        asyncio.run(service.shutdown())
        # retry-loop body after shutdown
        if service._claim_monitor_start():
            with mock.patch.object(card_monitoring, "CardMonitor", CountingCardMonitor):
                service._start_monitor()
        assert calls == []

    def test_start_monitor_failure_releases_claim(self):
        """A failed start must roll the claim back so it can be retried."""
        service = self._make_service()
        with mock.patch.object(
            service, "_start_monitor", side_effect=RuntimeError("boom")
        ):
            with pytest.raises(RuntimeError):
                service._try_start_monitor()
        assert service.is_polling is False
