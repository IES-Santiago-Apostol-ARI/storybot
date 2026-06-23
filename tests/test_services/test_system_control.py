"""Tests for system_control.poweroff().

Verifies (D-03 / RESEARCH Q7):
- poweroff() invokes asyncio.create_subprocess_exec with the configured command
- poweroff() is an awaitable coroutine the callers can await

The subprocess seam is monkeypatched — the real /sbin/poweroff is never run.
"""

import inspect
from unittest.mock import AsyncMock

import pytest

from app.config import ConfigManager


class TestPoweroff:
    """system_control.poweroff() — the shared monkeypatch seam."""

    @pytest.mark.asyncio
    async def test_poweroff_runs_configured_command(self, monkeypatch):
        """poweroff() awaits create_subprocess_exec with the unpacked command."""
        from app.services import system_control

        mock_exec = AsyncMock()
        monkeypatch.setattr(system_control.asyncio, "create_subprocess_exec", mock_exec)

        await system_control.poweroff()

        expected = ConfigManager().load().poweroff_cmd
        mock_exec.assert_awaited_once_with(*expected)

    @pytest.mark.asyncio
    async def test_poweroff_is_awaitable(self, monkeypatch):
        """poweroff() is async so callers can `await system_control.poweroff()`."""
        from app.services import system_control

        assert inspect.iscoroutinefunction(system_control.poweroff)

        monkeypatch.setattr(
            system_control.asyncio, "create_subprocess_exec", AsyncMock()
        )
        # Awaiting it must not raise.
        await system_control.poweroff()
