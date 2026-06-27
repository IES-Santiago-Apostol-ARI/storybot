"""Tests for swap_orchestrator — AC-3 + AC-6 (orchestrator failure modes)."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.swap_orchestrator import (
    LlamaRelaunchError,
    SwapOrchestrator,
)


def _make_subprocess_mock(returncode=0, stdout=b"", stderr=b""):
    proc = AsyncMock()
    proc.wait = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    return proc


@pytest.fixture
def orchestrator():
    return SwapOrchestrator()


class TestSuccessPath:
    """Full happy-path: stop llama → worker → start llama → health check."""

    @patch("app.services.swap_orchestrator._wait_for_llama_health", return_value=True)
    @patch("app.services.swap_orchestrator.asyncio.create_subprocess_exec")
    async def test_returns_paths_on_success(self, mock_exec, mock_health, orchestrator):
        stop_proc = _make_subprocess_mock()
        worker_output = json.dumps(
            {
                "status": "ok",
                "preview": "/tmp/test/cover-preview.png",
                "print": "/tmp/test/cover-print.png",
                "gen_seconds": 9.5,
            }
        ).encode()
        worker_proc = _make_subprocess_mock(stdout=worker_output)
        start_proc = _make_subprocess_mock()

        mock_exec.side_effect = [stop_proc, worker_proc, start_proc]

        result = await orchestrator.generate_cover_for_story(
            "test-story", "positive", "negative", 42
        )

        assert result[0] is not None
        assert result[1] is not None
        assert result[2] == 9.5
        assert mock_exec.call_count == 3

    @patch("app.services.swap_orchestrator._wait_for_llama_health", return_value=True)
    @patch("app.services.swap_orchestrator.asyncio.create_subprocess_exec")
    async def test_stop_before_start_order(self, mock_exec, mock_health, orchestrator):
        """Verify systemctl stop is called before worker, start after."""
        stop_proc = _make_subprocess_mock()
        worker_output = json.dumps(
            {
                "status": "ok",
                "preview": "/a.png",
                "print": "/b.png",
                "gen_seconds": 5.0,
            }
        ).encode()
        worker_proc = _make_subprocess_mock(stdout=worker_output)
        start_proc = _make_subprocess_mock()

        mock_exec.side_effect = [stop_proc, worker_proc, start_proc]

        await orchestrator.generate_cover_for_story("s1", "p", "n", 1)

        # First call: stop llama, second: worker, third: start llama
        first_cmd = mock_exec.call_args_list[0]
        assert "stop" in first_cmd[0]
        assert "llama-server" in first_cmd[0]

        second_cmd = mock_exec.call_args_list[1]
        assert "sd_cover_worker" in str(second_cmd)

        third_cmd = mock_exec.call_args_list[2]
        assert "start" in third_cmd[0]
        assert "llama-server" in third_cmd[0]


class TestWorkerFailure:
    """Worker exits non-zero → still relaunches llama."""

    @patch("app.services.swap_orchestrator._wait_for_llama_health", return_value=True)
    @patch("app.services.swap_orchestrator.asyncio.create_subprocess_exec")
    async def test_worker_nonzero_returns_none_tuple(
        self, mock_exec, mock_health, orchestrator
    ):
        stop_proc = _make_subprocess_mock()
        worker_proc = _make_subprocess_mock(
            returncode=1, stderr=b'{"status":"error","reason":"OOM"}\n'
        )
        start_proc = _make_subprocess_mock()

        mock_exec.side_effect = [stop_proc, worker_proc, start_proc]

        result = await orchestrator.generate_cover_for_story("fail-story", "p", "n", 1)

        assert result == (None, None, None)
        # Verify start was still called (crash-safe relaunch)
        third_cmd = mock_exec.call_args_list[2]
        assert "start" in third_cmd[0]

    @patch("app.services.swap_orchestrator._wait_for_llama_health", return_value=True)
    @patch("app.services.swap_orchestrator.asyncio.create_subprocess_exec")
    async def test_worker_failure_logs_to_stderr(
        self, mock_exec, mock_health, orchestrator, capsys
    ):
        stop_proc = _make_subprocess_mock()
        worker_proc = _make_subprocess_mock(
            returncode=1, stderr=b'{"status":"error","reason":"OOM"}\n'
        )
        start_proc = _make_subprocess_mock()

        mock_exec.side_effect = [stop_proc, worker_proc, start_proc]

        await orchestrator.generate_cover_for_story("fail-story", "p", "n", 1)

        captured = capsys.readouterr()
        log = json.loads(captured.err.strip().split("\n")[-1])
        assert log["event"] == "cover_failed"
        assert log["story_id"] == "fail-story"


class TestLlamaRelaunchTimeout:
    """Health check fails → raises LlamaRelaunchError."""

    @patch("app.services.swap_orchestrator._wait_for_llama_health", return_value=False)
    @patch("app.services.swap_orchestrator.asyncio.create_subprocess_exec")
    async def test_raises_llama_relaunch_error(
        self, mock_exec, mock_health, orchestrator
    ):
        stop_proc = _make_subprocess_mock()
        worker_output = json.dumps(
            {
                "status": "ok",
                "preview": "/a.png",
                "print": "/b.png",
                "gen_seconds": 5.0,
            }
        ).encode()
        worker_proc = _make_subprocess_mock(stdout=worker_output)
        start_proc = _make_subprocess_mock()

        mock_exec.side_effect = [stop_proc, worker_proc, start_proc]

        with pytest.raises(LlamaRelaunchError):
            await orchestrator.generate_cover_for_story("timeout-story", "p", "n", 1)


class TestWorkerTimeoutAlwaysRestartsLlama:
    """SD worker exceeding the internal timeout must not leave llama dead.

    Regression: generate.py wrapped the whole swap in asyncio.wait_for(); a
    long SD cover got cancelled AFTER llama was stopped but BEFORE the restart,
    leaving llama-server permanently dead so every later generation failed with
    'Failed to connect to llama-server'. The restart now lives in a finally and
    the worker is bounded by an internal timeout.
    """

    @patch("app.services.swap_orchestrator._wait_for_llama_health", return_value=True)
    @patch("app.services.swap_orchestrator.asyncio.create_subprocess_exec")
    async def test_restarts_llama_when_worker_times_out(
        self, mock_exec, mock_health, orchestrator, monkeypatch
    ):
        monkeypatch.setattr("app.services.swap_orchestrator.WORKER_TIMEOUT_S", 0.05)
        stop_proc = _make_subprocess_mock()

        async def slow_communicate(input=None):
            await asyncio.sleep(5)
            return (b"", b"")

        worker_proc = _make_subprocess_mock()
        worker_proc.communicate = slow_communicate
        worker_proc.kill = MagicMock()
        start_proc = _make_subprocess_mock()

        mock_exec.side_effect = [stop_proc, worker_proc, start_proc]

        result = await orchestrator.generate_cover_for_story("slow-story", "p", "n", 1)

        # Cover failed, but llama-server start was still issued (crash-safe).
        assert result == (None, None, None)
        assert mock_exec.call_count == 3
        third_cmd = mock_exec.call_args_list[2]
        assert "start" in third_cmd[0]
        assert "llama-server" in third_cmd[0]
        # Orphaned worker killed so it stops holding VRAM.
        worker_proc.kill.assert_called_once()


class TestEnsureLlamaRunning:
    """Self-heal: generation can bring llama back if a prior swap left it dead."""

    @patch("app.services.swap_orchestrator.asyncio.create_subprocess_exec")
    async def test_starts_llama_when_down(self, mock_exec, orchestrator):
        start_proc = _make_subprocess_mock()
        mock_exec.return_value = start_proc

        with (
            patch(
                "app.services.swap_orchestrator._llama_is_healthy",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "app.services.swap_orchestrator._wait_for_llama_health",
                new=AsyncMock(return_value=True),
            ),
        ):
            ok = await orchestrator.ensure_llama_running()

        assert ok is True
        assert mock_exec.call_count == 1
        cmd = mock_exec.call_args_list[0]
        assert "start" in cmd[0]
        assert "llama-server" in cmd[0]

    @patch("app.services.swap_orchestrator.asyncio.create_subprocess_exec")
    async def test_noop_when_already_healthy(self, mock_exec, orchestrator):
        with patch(
            "app.services.swap_orchestrator._llama_is_healthy",
            new=AsyncMock(return_value=True),
        ):
            ok = await orchestrator.ensure_llama_running()

        assert ok is True
        mock_exec.assert_not_called()

    @patch("app.services.swap_orchestrator.asyncio.create_subprocess_exec")
    async def test_skips_when_swap_in_progress(self, mock_exec, orchestrator):
        """A cover swap intentionally has llama down — don't fight it."""
        await orchestrator._lock.acquire()
        try:
            ok = await orchestrator.ensure_llama_running()
        finally:
            orchestrator._lock.release()

        assert ok is False
        mock_exec.assert_not_called()

    @patch("app.services.swap_orchestrator.asyncio.create_subprocess_exec")
    async def test_holds_lock_during_restart(self, mock_exec, orchestrator):
        """The lock MUST be held while llama is restarting so a cover swap can't
        start mid-restart and fight for VRAM — and released afterward."""
        mock_exec.return_value = _make_subprocess_mock()
        observed = {}

        async def health_wait(_timeout):
            observed["locked_during_restart"] = orchestrator._lock.locked()
            return True

        with (
            patch(
                "app.services.swap_orchestrator._llama_is_healthy",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "app.services.swap_orchestrator._wait_for_llama_health",
                new=health_wait,
            ),
        ):
            ok = await orchestrator.ensure_llama_running()

        assert ok is True
        assert observed["locked_during_restart"] is True
        assert orchestrator._lock.locked() is False  # released afterward


class TestBusyLock:
    """Concurrent invocation rejected — returns (None, None, None)."""

    @patch("app.services.swap_orchestrator._wait_for_llama_health", return_value=True)
    @patch("app.services.swap_orchestrator.asyncio.create_subprocess_exec")
    async def test_second_call_rejected_when_busy(
        self, mock_exec, mock_health, orchestrator, capsys
    ):
        # Make the first call slow (worker never completes during test)
        stop_proc = _make_subprocess_mock()

        async def slow_communicate(input=None):
            await asyncio.sleep(10)
            return (b"", b"")

        worker_proc = _make_subprocess_mock()
        worker_proc.communicate = slow_communicate
        start_proc = _make_subprocess_mock()

        mock_exec.side_effect = [stop_proc, worker_proc, start_proc]

        # Start first call in background
        task1 = asyncio.create_task(
            orchestrator.generate_cover_for_story("s1", "p", "n", 1)
        )

        # Give it time to acquire the lock
        await asyncio.sleep(0.1)

        # Second call should be rejected immediately
        result2 = await orchestrator.generate_cover_for_story("s2", "p", "n", 2)
        assert result2 == (None, None, None)

        captured = capsys.readouterr()
        assert "cover_dropped_busy" in captured.err

        # Clean up first task
        task1.cancel()
        try:
            await task1
        except asyncio.CancelledError:
            pass
