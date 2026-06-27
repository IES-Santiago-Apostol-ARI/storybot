"""Tests for hardware manager."""
from unittest.mock import AsyncMock, patch

import pytest

from app.services.base import HardwareService
from app.services.hardware_manager import HardwareManager


class MockService(HardwareService):
    """Mock hardware service for testing."""

    def __init__(self, name: str, is_mock: bool = True):
        self._name = name
        self._is_mock = is_mock
        self._initialized = False
        self._error = None

    @property
    def is_mock(self) -> bool:
        return self._is_mock

    @property
    def name(self) -> str:
        return self._name

    async def get_status(self) -> dict:
        if self._error:
            return {
                "name": self._name,
                "is_mock": self._is_mock,
                "status": "error",
                "error_message": self._error
            }
        return {
            "name": self._name,
            "is_mock": self._is_mock,
            "status": "ok" if self._initialized else "not_connected"
        }

    async def initialize(self) -> None:
        self._initialized = True

    async def shutdown(self) -> None:
        self._initialized = False


@pytest.fixture
async def hardware_manager():
    """Create a HardwareManager instance."""
    manager = HardwareManager()
    yield manager
    # Cleanup
    await manager.shutdown()


class TestHardwareManager:
    """Test HardwareManager functionality."""

    @pytest.mark.asyncio
    async def test_get_status_returns_dict_with_service_states(self, hardware_manager):
        """HardwareManager.get_status() returns dict with service states."""
        status = await hardware_manager.get_status()
        assert isinstance(status, dict)
        assert "hardware" in status
        assert "uptime_seconds" in status
        assert "version" in status

    @pytest.mark.asyncio
    async def test_rescan_triggers_detection_of_all_services(
        self, hardware_manager, monkeypatch
    ):
        """HardwareManager.rescan() triggers detection of all services."""
        # detect_hardware must be called before rescan per new contract (Plan 17-03).
        # Use monkeypatch so TESTING is restored to its session value afterward —
        # a bare ``del os.environ["TESTING"]`` leaks and breaks later tests that
        # depend on the conftest-set TESTING (e.g. the LED factory mock path).
        monkeypatch.setenv("TESTING", "1")
        await hardware_manager.detect_hardware(ai_enabled=True)
        monkeypatch.delenv("TESTING")

        # Register a mock service
        mock_service = MockService("test_service")
        hardware_manager.register_service("test_service", mock_service)

        # Rescan should trigger detection
        await hardware_manager.rescan()

        # Verify service was detected
        status = await hardware_manager.get_status()
        assert "test_service" in status["hardware"]

    @pytest.mark.asyncio
    async def test_register_service_adds_to_registry(self, hardware_manager):
        """Registering a service adds it to the registry."""
        mock_service = MockService("nfc")
        hardware_manager.register_service("nfc", mock_service)

        status = await hardware_manager.get_status()
        assert "nfc" in status["hardware"]

    @pytest.mark.asyncio
    async def test_shutdown_cleans_up_all_services(self, hardware_manager):
        """HardwareManager.shutdown() cleans up all services."""
        mock_service = MockService("audio")
        await mock_service.initialize()
        hardware_manager.register_service("audio", mock_service)

        # Verify service is initialized
        status_before = await mock_service.get_status()
        assert status_before["status"] == "ok"

        # Shutdown manager
        await hardware_manager.shutdown()

        # Verify service was cleaned up
        status_after = await mock_service.get_status()
        assert status_after["status"] == "not_connected"


class TestDetectHardwareAiGated:
    """Tests for detect_hardware(ai_enabled) TTS gating (Plan 17-03, CONTEXT.md D-14/D-15/D-16)."""

    @pytest.fixture
    def hw(self):
        """Create a fresh HardwareManager for each test."""
        return HardwareManager()

    @pytest.mark.asyncio
    async def test_signature_requires_ai_enabled_argument(self, hw, monkeypatch):
        """Calling detect_hardware() with no argument raises TypeError (D-15: no default)."""
        monkeypatch.setenv("TESTING", "1")
        with pytest.raises(TypeError):
            await hw.detect_hardware()

    @pytest.mark.asyncio
    async def test_ai_enabled_true_registers_tts_service(self, hw, monkeypatch):
        """When ai_enabled=True, TTS is instantiated and registered (preserves Phase 16 behavior)."""
        monkeypatch.setenv("TESTING", "1")
        await hw.detect_hardware(ai_enabled=True)
        status = await hw.get_status()
        assert "tts" in status["hardware"], (
            "Plan 17-03: tts must be registered when ai_enabled=True"
        )

    @pytest.mark.asyncio
    async def test_ai_enabled_false_does_not_register_tts_service(self, hw, monkeypatch):
        """When ai_enabled=False, tts is NOT registered and get_status omits it (D-16)."""
        monkeypatch.setenv("TESTING", "1")
        await hw.detect_hardware(ai_enabled=False)
        status = await hw.get_status()
        assert "tts" not in status["hardware"], (
            "Plan 17-03: tts must NOT be in hardware status when ai_enabled=False (D-16)"
        )

    @pytest.mark.asyncio
    async def test_ai_enabled_false_does_not_call_tts_initialize(self, hw, monkeypatch):
        """TTSEngine.initialize is never called when ai_enabled=False (D-14: no RAM cost)."""
        monkeypatch.setenv("TESTING", "1")
        with patch("app.services.tts_engine.TTSEngine") as MockTTS:
            MockTTS.return_value.initialize = AsyncMock()
            await hw.detect_hardware(ai_enabled=False)
            MockTTS.assert_not_called()

    @pytest.mark.asyncio
    async def test_ai_enabled_false_still_registers_nfc_led_audio(self, hw, monkeypatch):
        """Non-TTS peripherals are untouched by ai_enabled=False (D-15)."""
        monkeypatch.setenv("TESTING", "1")
        await hw.detect_hardware(ai_enabled=False)
        status = await hw.get_status()
        for key in ("nfc", "led", "audio"):
            assert key in status["hardware"], (
                f"Plan 17-03: {key} must still be registered when ai_enabled=False"
            )

    @pytest.mark.asyncio
    async def test_rescan_preserves_ai_enabled_false(self, hw, monkeypatch):
        """rescan() does not forget that ai_enabled=False (CONTEXT.md Deferred Ideas)."""
        monkeypatch.setenv("TESTING", "1")
        await hw.detect_hardware(ai_enabled=False)
        await hw.rescan()
        status = await hw.get_status()
        assert "tts" not in status["hardware"], (
            "Plan 17-03: rescan must preserve ai_enabled=False — tts still absent"
        )

    @pytest.mark.asyncio
    async def test_rescan_preserves_ai_enabled_true(self, hw, monkeypatch):
        """rescan() preserves ai_enabled=True — tts remains registered."""
        monkeypatch.setenv("TESTING", "1")
        await hw.detect_hardware(ai_enabled=True)
        await hw.rescan()
        status = await hw.get_status()
        assert "tts" in status["hardware"], (
            "Plan 17-03: rescan must preserve ai_enabled=True — tts still present"
        )
