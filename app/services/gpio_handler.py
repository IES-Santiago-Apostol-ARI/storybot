"""GPIO button service with real and mock implementations.

Bridges Jetson.GPIO edge events to an asyncio.Queue via call_soon_threadsafe,
following the HardwareService Mock/Real pattern.
"""

import asyncio
import os
import platform

from app.config import ConfigManager
from app.services.base import HardwareService

settings = ConfigManager().load()


class GPIOButtonService(HardwareService):
    """Protocol for GPIO button service."""

    @property
    def is_mock(self) -> bool:
        """Return True if this is a mock service."""
        ...

    def trigger(self, name: str) -> None:
        """Trigger a button press by name (mock seam).

        Args:
            name: Button name (e.g., "power", "interrupt").
        """
        ...


def _real_gpio_available() -> bool:
    """Pure monkeypatchable probe for GPIO hardware availability.

    Returns True if on aarch64 and Jetson.GPIO is importable.
    Mirrors _real_led_available in led_controller.py.
    """
    try:
        return (
            platform.machine() == "aarch64"
            and bool(__import__("Jetson.GPIO"))
        )
    except Exception:
        return False


def create_gpio_service() -> GPIOButtonService:
    """Factory — never raises (mirrors create_led_service).

    Returns:
        - MockGPIOButtonService when TESTING env is set.
        - MockGPIOButtonService when probe fails (not aarch64 or Jetson.GPIO missing).
        - RealGPIOButtonService otherwise.
    """
    if os.environ.get("TESTING"):
        return MockGPIOButtonService()

    if not _real_gpio_available():
        return MockGPIOButtonService()

    return RealGPIOButtonService()


class RealGPIOButtonService(GPIOButtonService):
    """Real GPIO button service using Jetson.GPIO edge detection.

    Configures 4 pins (BOARD mode) with internal pull-up and falling-edge
    detection. Edge callbacks on the GPIO thread call into the asyncio loop
    via loop.call_soon_threadsafe to enqueue the button name.
    """

    def __init__(self) -> None:
        """Initialize real GPIO service."""
        self._pin_to_name: dict[int, str] = {}
        self._queue: asyncio.Queue | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def is_mock(self) -> bool:
        """Return False - this is real GPIO service."""
        return False

    async def initialize(self, queue: asyncio.Queue) -> None:
        """Configure pins and arm edge detection.

        Args:
            queue: Shared asyncio.Queue for button events.
        """
        import Jetson.GPIO as GPIO

        self._queue = queue
        self._loop = asyncio.get_running_loop()

        # Pin-to-name map from Settings defaults
        pin_map = {
            settings.gpio_power_pin: "power",
            settings.gpio_interrupt_pin: "interrupt",
            settings.gpio_image_pin: "image",
            settings.gpio_animation_pin: "animation",
        }
        self._pin_to_name = pin_map

        GPIO.setmode(GPIO.BOARD)
        for pin in pin_map:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
            GPIO.add_event_detect(
                pin,
                GPIO.RISING,
                callback=self._edge_callback,
                bouncetime=settings.gpio_bounce_ms,
            )

    def _edge_callback(self, pin: int) -> None:
        """Handle GPIO edge event on the GPIO thread.

        Looks up button name and enqueues via call_soon_threadsafe.
        """
        name = self._pin_to_name.get(pin)
        if name and self._loop is not None and self._queue is not None:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, name)

    async def run(self, queue: asyncio.Queue) -> None:
        """Background task — idle loop keeping the service alive.

        Edge callbacks remain armed while this task runs. Catches
        CancelledError and re-raises for clean shutdown.
        """
        try:
            while True:
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            raise

    async def shutdown(self) -> None:
        """Shutdown GPIO service — release pins."""
        try:
            import Jetson.GPIO as GPIO

            GPIO.cleanup()
        except Exception:
            pass

    async def get_status(self) -> dict:
        """Get GPIO service status."""
        return {
            "name": "gpio",
            "is_mock": self.is_mock,
            "status": "ok",
            "error_message": None,
        }

    def trigger(self, name: str) -> None:
        """Trigger a button press (not used in real service, protocol seam)."""
        # Real service uses edge detection; this is for the protocol surface.
        pass


class MockGPIOButtonService(GPIOButtonService):
    """Mock GPIO button service for testing without hardware."""

    def __init__(self) -> None:
        """Initialize mock GPIO service."""
        self._queue: asyncio.Queue | None = None

    @property
    def is_mock(self) -> bool:
        """Return True - this is mock GPIO service."""
        return True

    async def initialize(self, queue: asyncio.Queue) -> None:
        """Initialize mock GPIO service — store queue reference."""
        self._queue = queue

    def trigger(self, name: str) -> None:
        """Simulate a button press by enqueuing the button name.

        Args:
            name: Button name (e.g., "power", "interrupt").
        """
        if self._queue is not None:
            self._queue.put_nowait(name)

    async def run(self, queue: asyncio.Queue) -> None:
        """Background idle task — sleeps until cancelled.

        Catches CancelledError and re-raises for clean shutdown.
        """
        try:
            while True:
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            raise

    async def shutdown(self) -> None:
        """Shutdown mock GPIO service — no-op."""
        pass

    async def get_status(self) -> dict:
        """Get mock GPIO service status."""
        return {
            "name": "gpio",
            "is_mock": self.is_mock,
            "status": "ok",
            "error_message": None,
        }
