"""System control service — poweroff and other system-level operations.

Provides ``system_control.poweroff()`` which runs the configured poweroff
command via ``asyncio.create_subprocess_exec`` so the FastAPI event loop is
never blocked waiting for the OS to shut down. This module-level coroutine is
the single monkeypatch seam (D-03) shared by the GpioDispatcher power button
handler and ``POST /api/system/poweroff`` — tests patch it and never actually
power off.
"""

import asyncio

from app.config import ConfigManager

settings = ConfigManager().load()


async def poweroff() -> None:
    """Execute the configured system poweroff command.

    Runs ``settings.poweroff_cmd`` (``["/usr/bin/sudo", "/sbin/poweroff"]`` by
    default) via ``asyncio.create_subprocess_exec`` so the event loop is not
    held while the OS shuts down (RESEARCH Q7 / D-03).
    """
    await asyncio.create_subprocess_exec(*settings.poweroff_cmd)
