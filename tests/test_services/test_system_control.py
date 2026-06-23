"""Tests for system_control.poweroff().

Verifies:
- poweroff() executes the configured command via subprocess.Popen
- Process is started detached (start_new_session=True)
- Command matches settings.poweroff_cmd
"""

from unittest.mock import patch

import pytest


class TestPoweroff:
    """system_control.poweroff() function."""

    @pytest.mark.asyncio
    async def test_poweroff_runs_command(self):
        """system_control.poweroff() executes the configured poweroff command."""
        from app.services import system_control

        with patch("subprocess.Popen") as mock_popen:
            await system_control.poweroff()
            mock_popen.assert_called_once()

    @pytest.mark.asyncio
    async def test_poweroff_uses_configured_command(self):
        """poweroff uses the poweroff_cmd from settings."""
        from app.services import system_control

        with patch("subprocess.Popen") as mock_popen:
            await system_control.poweroff()
            call_args = mock_popen.call_args
            # The command should be the configured poweroff_cmd
            assert call_args[0][0] == ["/usr/bin/sudo", "/sbin/poweroff"]

    @pytest.mark.asyncio
    async def test_poweroff_starts_detached_process(self):
        """poweroff starts a detached process (start_new_session=True)."""
        from app.services import system_control

        with patch("subprocess.Popen") as mock_popen:
            await system_control.poweroff()
            call_kwargs = mock_popen.call_args[1]
            assert call_kwargs.get("start_new_session") is True
