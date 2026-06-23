import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

POLL_INTERVAL = 5  # seconds

class BtMonitor:
    """
    Continuously tracks BT connection status and handles audio fallback.
    
    Implementation of Plan 28-02.
    """
    def __init__(
        self,
        manager,
        route_to_wired: Callable[[], Awaitable[Any]],
        probe: Callable[[str], Awaitable[bool]] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None
    ):
        self.manager = manager
        self.route_to_wired = route_to_wired
        self.probe = probe
        self.sleep = sleep or asyncio.sleep

        # Initial state
        self.sink = "bt"
        self.health_state = "connected"

    async def poll_once(self):
        """
        A single health check iteration.
        D-06: healthy IFF (BlueZ Connected == True AND bluez_output sink present).
        """
        speaker = await self.manager.get_last_speaker()
        if not speaker:
            # D-13: stop condition = no remembered speaker
            self._last_mac = None
            self._last_name = None
            return

        mac = speaker["mac"]
        device_name = speaker.get("name", "Unknown")
        self._last_mac = mac
        self._last_name = device_name

        try:
            # If no probe is provided, we use a default (which would check BlueZ/Pulse)
            # For testing, the probe is injected.
            is_healthy = await self._perform_probe(mac)
        except Exception as e:
            logger.error(f"bt_monitor_iter_failed: Probe exception for {mac}: {e}")
            # Pitfall 4: Swallow and stay alive.
            # We treat an exception as unhealthy to trigger fallback/retry safely.
            is_healthy = False

        if is_healthy:
            self.health_state = "connected"
            self.sink = "bt"
        else:
            # Unhealthy detection
            if self.sink == "bt":
                # AUDIO-05: Fallback to wired if we were on BT
                await self.route_to_wired()
                self.sink = "wired"
                self.health_state = "wired-fallback"
            elif self.health_state == "connected":
                # We are already on wired sink but some other health check failed
                self.health_state = "reconnecting"

            # D-07: Keep retrying connection even in fallback state
            try:
                await self.manager.connect(mac)
                # Note: we don't set health_state to connected here because
                # the next probe will verify if it actually worked.
            except Exception as e:
                logger.debug(f"Reconnection attempt failed for {mac}: {e}")

    async def _perform_probe(self, mac: str) -> bool:
        """Helper to run provided probe or default logic."""
        if self.probe:
            return await self.probe(mac)
        # Default logic would go here (e.g. calling bt_manager internals)
        # For this plan, the probe is the primary extension point for the health check.
        return await self.manager.is_connected(mac)

    async def run(self):
        """Main loop: poll -> sleep -> repeat."""
        while True:
            try:
                await self.poll_once()
            except Exception as e:
                # Pitfall 4: Ensure the monitor never dies
                logger.exception(f"bt_monitor_loop_error: {e}")

            await self.sleep(POLL_INTERVAL)
            # Ensure we yield to the event loop, especially when using fake/instant sleeps in tests
            await asyncio.sleep(0)

    def status(self) -> dict[str, Any]:
        """D-14: Surface current health and sink state."""
        return {
            "sink": self.sink,
            "health_state": self.health_state,
            "device_mac": getattr(self, "_last_mac", None),
            "device_name": getattr(self, "_last_name", None),
        }

