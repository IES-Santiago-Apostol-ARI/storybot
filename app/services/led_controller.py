"""LED controller service with real and mock implementations."""

import json
import os
import platform
import sys

from app.config import ConfigManager
from app.services.base import HardwareService
from app.services.led_spi import SpiWriter, encode_ws2812

settings = ConfigManager().load()


class LEDService(HardwareService):
    """Protocol for LED service."""

    @property
    def is_mock(self) -> bool:
        """Return True if this is a mock service."""
        ...

    async def set_color(self, r: int, g: int, b: int) -> None:
        """Set LED color.

        Args:
            r: Red component (0-255).
            g: Green component (0-255).
            b: Blue component (0-255).
        """
        ...

    def get_color(self) -> tuple[int, int, int]:
        """Get current LED color.

        Returns:
            Tuple of (r, g, b) values.
        """
        ...

    async def turn_off(self) -> None:
        """Turn off LEDs."""
        ...


def _log_event(event: str, **kwargs: object) -> None:
    """Structured JSON log to stderr (same pattern as bt_manager)."""
    print(
        json.dumps({"event": event, **kwargs}),
        file=sys.stderr,
    )


def _spi_node(bus: int, dev: int) -> str:
    """Return the SPI device node path."""
    return f"/dev/spidev{bus}.{dev}"


def _real_led_available(bus: int, dev: int) -> bool:
    """Pure monkeypatchable probe for LED hardware availability.
    Returns True if on aarch64 and the SPI node exists and is writable.
    """
    try:
        node = _spi_node(bus, dev)
        return (
            platform.machine() == "aarch64"
            and os.path.exists(node)
            and os.access(node, os.W_OK)
        )
    except OSError:
        return False


class RealLEDService(LEDService):
    """Real LED service driver for WS2812B strips via SPI.

    Holds an N-pixel framebuffer and drives the encoder (encode_ws2812)
    via SpiWriter on the real hardware path.
    """

    def __init__(self) -> None:
        """Initialize real LED service."""
        self._color: tuple[int, int, int] = (0, 0, 0)
        self._available = False
        self._framebuffer = [(0, 0, 0)] * settings.led_count
        self._writer: SpiWriter | None = None

    @property
    def is_mock(self) -> bool:
        """Return False - this is real LED service."""
        return False

    async def set_color(self, r: int, g: int, b: int) -> None:
        """Set LED color and write to hardware if available.
        RGB-in contract preserved at the boundary (D-04).
        """
        # Clamp values to 0-255
        r = max(0, min(255, r))
        g = max(0, min(255, g))
        b = max(0, min(255, b))

        self._color = (r, g, b)
        self._framebuffer = [(r, g, b)] * settings.led_count

        if self._available and self._writer:
            # Sync write to SPI (Phase 32 wraps this with asyncio.to_thread).
            self._writer.write(
                encode_ws2812(
                    self._framebuffer,
                    count=settings.led_count,
                    cap=settings.led_max_brightness,
                    gamma=settings.led_gamma,
                    order=settings.led_color_order,
                    speed_hz=settings.led_spi_speed_hz,
                )
            )

    def get_color(self) -> tuple[int, int, int]:
        """Get current LED color (RGB)."""
        return self._color

    async def turn_off(self) -> None:
        """Turn off LEDs."""
        await self.set_color(0, 0, 0)

    async def get_status(self) -> dict:
        """Get LED service status."""
        if not self._available:
            return {
                "name": "led",
                "is_mock": self.is_mock,
                "status": "not_connected",
                "error_message": "LED hardware not verified",
            }

        return {
            "name": "led",
            "is_mock": self.is_mock,
            "status": "ok",
            "error_message": None,
        }

    async def initialize(self) -> None:
        """Initialize LED service and construct lazy SpiWriter."""
        try:
            # Construct writer only on real path to avoid spidev import on x86.
            self._writer = SpiWriter(
                bus=settings.led_spi_bus,
                dev=settings.led_spi_dev,
                speed_hz=settings.led_spi_speed_hz,
            )
            self._available = True
        except (RuntimeError, OSError, ImportError) as e:
            _log_event("led_init_fallback", reason=type(e).__name__)
            self._available = False

    async def shutdown(self) -> None:
        """Shutdown LED service."""
        await self.turn_off()
        if self._writer:
            self._writer.close()


class MockLEDService(LEDService):
    """Mock LED service for testing without hardware."""

    def __init__(self) -> None:
        """Initialize mock LED service."""
        self._color: tuple[int, int, int] = (0, 0, 0)

    @property
    def is_mock(self) -> bool:
        """Return True - this is mock LED service."""
        return True

    async def set_color(self, r: int, g: int, b: int) -> None:
        """Set mock LED color (tracks state only)."""
        # Clamp values to 0-255
        r = max(0, min(255, r))
        g = max(0, min(255, g))
        b = max(0, min(255, b))

        self._color = (r, g, b)

    def get_color(self) -> tuple[int, int, int]:
        """Get current mock LED color."""
        return self._color

    async def turn_off(self) -> None:
        """Turn off mock LEDs."""
        self._color = (0, 0, 0)

    async def get_status(self) -> dict:
        """Get mock LED service status."""
        return {
            "name": "led",
            "is_mock": self.is_mock,
            "status": "ok",
            "error_message": None,
        }

    async def initialize(self) -> None:
        """Initialize mock LED service."""
        self._color = (0, 0, 0)

    async def shutdown(self) -> None:
        """Shutdown mock LED service."""
        await self.turn_off()


def create_led_service() -> LEDService:
    """Factory — never raises (mirrors create_bt_manager / create_printer_service).

    Returns:
        - MockLEDService when TESTING env is set.
        - MockLEDService when probe fails (not aarch64, node missing, or not W_OK).
        - RealLEDService otherwise.
    """
    if os.environ.get("TESTING"):
        return MockLEDService()

    bus = settings.led_spi_bus
    dev = settings.led_spi_dev

    if not _real_led_available(bus, dev):
        _log_event("led_init_fallback", reason="no_spi_node")
        return MockLEDService()

    return RealLEDService()
