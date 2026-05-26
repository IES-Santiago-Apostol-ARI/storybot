"""Hardware service manager."""

import time

from app.models.system import HardwareState, SystemStatus
from app.services.base import HardwareService


class HardwareManager:
    """Manage hardware services and detect hardware."""

    def __init__(self) -> None:
        """Initialize hardware manager."""
        self._services: dict[str, HardwareService] = {}
        self._start_time = time.time()
        self._version = "0.1.0"

    def register_service(self, name: str, service: HardwareService) -> None:
        """Register a hardware service.

        Args:
            name: Service name (e.g., "nfc", "led", "audio")
            service: HardwareService instance
        """
        self._services[name] = service

    async def get_status(self) -> dict:
        """Get status of all hardware services.

        Returns:
            dict with SystemStatus data
        """
        hardware_states = {}

        for name, service in self._services.items():
            try:
                service_status = await service.get_status()
                hardware_states[name] = HardwareState(**service_status)
            except Exception as e:
                # If service fails to report status, mark as error
                hardware_states[name] = HardwareState(
                    name=name,
                    is_mock=getattr(service, "is_mock", True),
                    status="error",
                    error_message=str(e),
                )

        status = SystemStatus(
            hardware=hardware_states,
            uptime_seconds=time.time() - self._start_time,
            version=self._version,
        )
        return status.dict()

    async def detect_hardware(self, ai_enabled: bool) -> None:
        """Detect available hardware and register services.

        When ai_enabled is False, the Piper TTS engine is NOT loaded
        (CONTEXT.md D-14, D-15). Other peripherals always probe.
        """
        self._ai_enabled: bool = ai_enabled

        from app.services.audio_player import create_audio_player
        from app.services.led_controller import create_led_service
        from app.services.nfc_handler import create_nfc_service

        if ai_enabled:
            from app.services.tts_engine import TTSEngine

            # TTS: Always real, load model at startup (eager load)
            tts_engine = TTSEngine()
            await tts_engine.initialize()
            self.register_service("tts", tts_engine)

        # NFC: Try real, fall back to mock
        nfc_service = create_nfc_service()
        await nfc_service.initialize()
        self.register_service("nfc", nfc_service)

        # LED: Mock for now (hardware TBD)
        led_service = create_led_service()
        await led_service.initialize()
        self.register_service("led", led_service)

        # Audio: Try real, fall back to mock
        audio_service = create_audio_player()
        await audio_service.initialize()
        self.register_service("audio", audio_service)

    async def rescan(self) -> dict:
        """Rescan for hardware changes.

        Returns:
            Updated SystemStatus dict
        """
        await self.detect_hardware(ai_enabled=self._ai_enabled)
        return await self.get_status()

    async def shutdown(self) -> None:
        """Shutdown all hardware services."""
        for service in self._services.values():
            try:
                await service.shutdown()
            except Exception:
                # Ignore shutdown errors
                pass
        self._services.clear()
