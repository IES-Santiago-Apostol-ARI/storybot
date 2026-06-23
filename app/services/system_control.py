"""System control service — poweroff and other system-level operations.

Provides system_control.poweroff() which runs the configured poweroff command
as a detached subprocess so the FastAPI event loop is not blocked waiting for
the OS to shut down.
"""

import subprocess

from app.config import ConfigManager

settings = ConfigManager().load()


async def poweroff() -> None:
    """Execute the system poweroff command as a detached process.

    Starts ``settings.poweroff_cmd`` via ``subprocess.Popen`` with
    ``start_new_session=True`` so the process is detached from the
    FastAPI event loop and can continue after the app exits.
    """
    subprocess.Popen(
        settings.poweroff_cmd,
        start_new_session=True,
    )
