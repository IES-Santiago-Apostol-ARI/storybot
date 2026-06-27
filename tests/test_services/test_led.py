"""Tests for LED controller service."""

from unittest.mock import patch

import pytest

from app.services.led_controller import (
    MockLEDService,
    RealLEDService,
    create_led_service,
)


@pytest.fixture
def mock_led_service():
    """Create a mock LED service for testing."""
    return MockLEDService()


@pytest.fixture
def real_led_service():
    """Create a real LED service for testing."""
    return RealLEDService()


class TestMockLEDService:
    """Test mock LED service functionality."""

    @pytest.mark.asyncio
    async def test_mock_led_service_initializes(self, mock_led_service):
        """Test that mock LED service can be created."""
        assert mock_led_service is not None
        assert hasattr(mock_led_service, "is_mock")
        assert hasattr(mock_led_service, "set_color")
        assert hasattr(mock_led_service, "get_color")
        assert hasattr(mock_led_service, "turn_off")

    @pytest.mark.asyncio
    async def test_mock_led_service_is_mock(self, mock_led_service):
        """Test that mock LED service reports as mock."""
        assert mock_led_service.is_mock is True

    @pytest.mark.asyncio
    async def test_mock_led_service_initial_color(self, mock_led_service):
        """Test initial color is black (off)."""
        color = mock_led_service.get_color()
        assert color == (0, 0, 0)

    @pytest.mark.asyncio
    async def test_mock_led_service_set_color(self, mock_led_service):
        """Test setting LED color."""
        await mock_led_service.set_color(255, 0, 0)  # Red
        color = mock_led_service.get_color()
        assert color == (255, 0, 0)

        await mock_led_service.set_color(0, 255, 0)  # Green
        color = mock_led_service.get_color()
        assert color == (0, 255, 0)

        await mock_led_service.set_color(0, 0, 255)  # Blue
        color = mock_led_service.get_color()
        assert color == (0, 0, 255)

    @pytest.mark.asyncio
    async def test_mock_led_service_turn_off(self, mock_led_service):
        """Test turning off LEDs."""
        await mock_led_service.set_color(255, 255, 255)
        assert mock_led_service.get_color() == (255, 255, 255)

        await mock_led_service.turn_off()
        assert mock_led_service.get_color() == (0, 0, 0)

    @pytest.mark.asyncio
    async def test_mock_led_service_get_status(self, mock_led_service):
        """Test getting mock LED service status."""
        status = await mock_led_service.get_status()
        assert "name" in status
        assert "is_mock" in status
        assert "status" in status
        assert status["name"] == "led"
        assert status["is_mock"] is True

    @pytest.mark.asyncio
    async def test_mock_led_service_initialize_and_shutdown(self, mock_led_service):
        """Test initialize and shutdown methods."""
        await mock_led_service.initialize()
        await mock_led_service.shutdown()
        assert mock_led_service.get_color() == (0, 0, 0)

    @pytest.mark.asyncio
    async def test_mock_led_service_clamps_color_values(self, mock_led_service):
        """Test that color values are clamped to 0-255."""
        await mock_led_service.set_color(300, -50, 128)
        color = mock_led_service.get_color()
        assert color == (255, 0, 128)


class TestRealLEDService:
    """Test real LED service functionality."""

    @pytest.mark.asyncio
    async def test_real_led_service_initializes(self, real_led_service):
        """Test that real LED service can be created."""
        assert real_led_service is not None
        assert hasattr(real_led_service, "is_mock")
        assert hasattr(real_led_service, "set_color")
        assert hasattr(real_led_service, "get_color")
        assert hasattr(real_led_service, "turn_off")

    @pytest.mark.asyncio
    async def test_real_led_service_is_not_mock(self, real_led_service):
        """Test that real LED service reports as not mock."""
        assert real_led_service.is_mock is False

    @pytest.mark.asyncio
    async def test_real_led_service_initial_color(self, real_led_service):
        """Test initial color is black (off)."""
        color = real_led_service.get_color()
        assert color == (0, 0, 0)

    @pytest.mark.asyncio
    async def test_real_led_service_set_color(self, real_led_service):
        """Test setting LED color."""
        await real_led_service.set_color(255, 128, 64)
        color = real_led_service.get_color()
        assert color == (255, 128, 64)

    @pytest.mark.asyncio
    async def test_real_led_service_clamps_color_values(self, real_led_service):
        """Test that color values are clamped to 0-255."""
        await real_led_service.set_color(500, -100, 128)
        color = real_led_service.get_color()
        assert color == (255, 0, 128)

    @pytest.mark.asyncio
    async def test_real_led_service_turn_off(self, real_led_service):
        """Test turning off LEDs."""
        await real_led_service.set_color(255, 255, 255)
        await real_led_service.turn_off()
        assert real_led_service.get_color() == (0, 0, 0)

    @pytest.mark.asyncio
    async def test_real_led_service_get_status_not_available(self, real_led_service):
        """Test get_status when hardware not available."""
        status = await real_led_service.get_status()
        assert status["name"] == "led"
        assert status["is_mock"] is False
        assert status["status"] == "not_connected"
        assert "not verified" in status["error_message"]

    @pytest.mark.asyncio
    async def test_real_led_service_get_status_available(self, real_led_service):
        """Test get_status when hardware is available."""
        real_led_service._available = True
        status = await real_led_service.get_status()
        assert status["status"] == "ok"
        assert status["error_message"] is None

    @pytest.mark.asyncio
    async def test_real_led_service_initialize(self, real_led_service, monkeypatch):
        """initialize() falls back to unavailable when the SpiWriter can't open.

        Force the SpiWriter construction to fail so the fallback branch is
        exercised deterministically — on a Jetson with real spidev present it
        would otherwise succeed and _available would be True.
        """

        def _boom(*args, **kwargs):
            raise RuntimeError("no spidev")

        monkeypatch.setattr("app.services.led_controller.SpiWriter", _boom)
        await real_led_service.initialize()
        assert real_led_service._available is False

    @pytest.mark.asyncio
    async def test_real_led_service_shutdown(self, real_led_service):
        """Test shutdown method turns off LEDs."""
        await real_led_service.set_color(100, 100, 100)
        await real_led_service.shutdown()
        assert real_led_service.get_color() == (0, 0, 0)


class TestCreateLEDService:
    """Test LED service factory function."""

    def test_create_led_service_returns_mock(self):
        """Test that create_led_service returns MockLEDService when the probe fails (TESTING=1 in conftest, D-07 deliberate update)."""
        service = create_led_service()
        assert isinstance(service, MockLEDService)
        assert service.is_mock is True

    def test_factory_returns_mock_on_x86(self, monkeypatch):
        """Test that factory returns mock on x86 architecture."""
        with patch("platform.machine", return_value="x86_64"):
            service = create_led_service()
            assert isinstance(service, MockLEDService)

    def test_factory_returns_mock_when_node_missing(self, monkeypatch):
        """Test that factory returns mock when SPI device node is missing."""
        with (
            patch("platform.machine", return_value="aarch64"),
            patch("os.path.exists", return_value=False),
        ):
            service = create_led_service()
            assert isinstance(service, MockLEDService)

    def test_factory_returns_mock_when_not_writable(self, monkeypatch):
        """Test that factory returns mock when SPI device node is not writable."""
        with (
            patch("platform.machine", return_value="aarch64"),
            patch("os.path.exists", return_value=True),
            patch("os.access", return_value=False),
        ):
            service = create_led_service()
            assert isinstance(service, MockLEDService)

    def test_factory_returns_real_when_all_gates_open(self, monkeypatch):
        """
        Test that factory returns RealLEDService when all gates are open.
        Strategy: patch the probe helper _real_led_available and mock SpiWriter
        to avoid spidev import errors on x86.
        """
        monkeypatch.delenv("TESTING", raising=False)
        with (
            patch("app.services.led_controller._real_led_available", return_value=True),
            patch("app.services.led_controller.SpiWriter", return_value=None),
        ):
            service = create_led_service()
            assert isinstance(service, RealLEDService)

    def test_factory_creates_new_instance_each_call(self):
        """Test that each factory call returns a distinct instance."""
        s1 = create_led_service()
        s2 = create_led_service()
        assert s1 is not s2

    def test_factory_never_raises_on_any_path(self, monkeypatch):
        """PLAT-03: Every monkeypatch combination returns without raising."""
        # Case 1: x86
        with patch("platform.machine", return_value="x86_64"):
            assert isinstance(create_led_service(), MockLEDService)

        # Case 2: aarch64 but missing node
        with (
            patch("platform.machine", return_value="aarch64"),
            patch("os.path.exists", return_value=False),
        ):
            assert isinstance(create_led_service(), MockLEDService)

        # Case 3: aarch64, node exists, not writable
        with (
            patch("platform.machine", return_value="aarch64"),
            patch("os.path.exists", return_value=True),
            patch("os.access", return_value=False),
        ):
            assert isinstance(create_led_service(), MockLEDService)

    def test_factory_testing_takes_precedence_over_real(self, monkeypatch):
        """TESTING beats everything — even if hardware is present."""
        monkeypatch.setenv("TESTING", "1")
        with (
            patch("app.services.led_controller._real_led_available", return_value=True),
            patch("app.services.led_controller.SpiWriter", return_value=None),
        ):
            service = create_led_service()
            assert isinstance(service, MockLEDService)
