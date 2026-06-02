"""Tests for update_manager — check, apply, version, rollback."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.models.updates import UpdateCheckResponse, UpdateVersionResponse
from app.services.update_manager import (
    MockUpdateManager,
    RealUpdateManager,
    UpdateManager,
    _find_uv,
    _run_uv,
    create_update_manager,
)

# ---------------------------------------------------------------------------
# Subprocess mock helper (same pattern as test_wifi_manager.py)
# ---------------------------------------------------------------------------


def _make_subprocess_mock(returncode=0, stdout=b"", stderr=b""):
    proc = AsyncMock()
    proc.wait = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    return proc


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class TestUpdateCheckResponseModel:
    """UpdateCheckResponse model validation."""

    def test_update_available(self):
        resp = UpdateCheckResponse(
            update_available=True,
            local_commit="abc1234",
            remote_commit="def5678",
        )
        assert resp.update_available is True
        assert resp.local_commit == "abc1234"
        assert resp.remote_commit == "def5678"
        assert resp.error is None

    def test_no_update_available(self):
        resp = UpdateCheckResponse(
            update_available=False,
            local_commit="abc1234",
            remote_commit="abc1234",
        )
        assert resp.update_available is False

    def test_with_error(self):
        resp = UpdateCheckResponse(
            update_available=False,
            local_commit="abc1234",
            remote_commit="",
            error="fetch failed",
        )
        assert resp.error == "fetch failed"

    def test_error_defaults_none(self):
        resp = UpdateCheckResponse(
            update_available=False,
            local_commit="abc",
            remote_commit="def",
        )
        assert resp.error is None


class TestUpdateVersionResponseModel:
    """UpdateVersionResponse model validation."""

    def test_version_response(self):
        resp = UpdateVersionResponse(version="v1.4.0-12-gabc", commit="abc1234")
        assert resp.version == "v1.4.0-12-gabc"
        assert resp.commit == "abc1234"


# ---------------------------------------------------------------------------
# check_update
# ---------------------------------------------------------------------------


class TestCheckUpdate:
    """RealUpdateManager.check_update() compares local vs remote HEAD."""

    @patch("app.services.update_manager.asyncio.create_subprocess_exec")
    async def test_update_available_when_hashes_differ(self, mock_exec):
        fetch_proc = _make_subprocess_mock(returncode=0)
        local_proc = _make_subprocess_mock(stdout=b"abc1234\n")
        remote_proc = _make_subprocess_mock(stdout=b"def5678\n")
        mock_exec.side_effect = [fetch_proc, local_proc, remote_proc]
        mgr = RealUpdateManager()
        result = await mgr.check_update()
        assert result["update_available"] is True
        assert result["local_commit"] == "abc1234"
        assert result["remote_commit"] == "def5678"

    @patch("app.services.update_manager.asyncio.create_subprocess_exec")
    async def test_no_update_when_hashes_same(self, mock_exec):
        fetch_proc = _make_subprocess_mock(returncode=0)
        local_proc = _make_subprocess_mock(stdout=b"abc1234\n")
        remote_proc = _make_subprocess_mock(stdout=b"abc1234\n")
        mock_exec.side_effect = [fetch_proc, local_proc, remote_proc]
        mgr = RealUpdateManager()
        result = await mgr.check_update()
        assert result["update_available"] is False
        assert result["local_commit"] == "abc1234"
        assert result["remote_commit"] == "abc1234"

    @patch("app.services.update_manager.asyncio.create_subprocess_exec")
    async def test_fetch_failure_returns_error(self, mock_exec):
        fetch_proc = _make_subprocess_mock(
            returncode=1, stderr=b"fatal: unable to connect"
        )
        mock_exec.return_value = fetch_proc
        mgr = RealUpdateManager()
        result = await mgr.check_update()
        assert result["update_available"] is False
        assert "error" in result


# ---------------------------------------------------------------------------
# apply_update (async generator)
# ---------------------------------------------------------------------------


class TestApplyUpdate:
    """RealUpdateManager.apply_update() yields SSE progress events."""

    @patch("app.services.update_manager.asyncio.create_subprocess_exec")
    async def test_successful_update_yields_all_stages(self, mock_exec):
        """Successful update goes through all stages in order."""
        head_proc = _make_subprocess_mock(stdout=b"abc1234\n")
        fetch_proc = _make_subprocess_mock(returncode=0)
        reset_proc = _make_subprocess_mock(returncode=0)
        uv_proc = _make_subprocess_mock(returncode=0)
        ruff_proc = _make_subprocess_mock(returncode=0)
        restart_proc = _make_subprocess_mock(returncode=0)
        mock_exec.side_effect = [
            head_proc,  # save HEAD (rev-parse HEAD)
            fetch_proc,  # git fetch origin --quiet
            reset_proc,  # git reset --hard origin/main
            uv_proc,  # uv sync
            ruff_proc,  # ruff check app/
            restart_proc,  # fire-and-forget restart
        ]
        mgr = RealUpdateManager()
        events = []
        async for event in mgr.apply_update():
            events.append(event)
        stages = [e["stage"] for e in events]
        assert "fetching" in stages
        assert "updating" in stages
        assert "syncing" in stages
        assert "checking" in stages
        assert "restarting" in stages
        # Last event should be done
        assert events[-1]["done"] is True
        assert events[-1]["stage"] == "restarting"

    @patch("app.services.update_manager.asyncio.create_subprocess_exec")
    async def test_rollback_on_fetch_failure(self, mock_exec):
        """Fetch failure during apply yields error (no rollback needed)."""
        head_proc = _make_subprocess_mock(stdout=b"abc1234\n")
        fetch_fail_proc = _make_subprocess_mock(
            returncode=1, stderr=b"fetch failed"
        )
        mock_exec.side_effect = [
            head_proc,  # save HEAD (rev-parse HEAD)
            fetch_fail_proc,  # git fetch fails
        ]
        mgr = RealUpdateManager()
        events = []
        async for event in mgr.apply_update():
            events.append(event)
        error_events = [e for e in events if e.get("stage") == "error"]
        assert len(error_events) == 1
        assert error_events[0]["error"] is not None

    @patch("app.services.update_manager.asyncio.create_subprocess_exec")
    async def test_rollback_on_reset_failure(self, mock_exec):
        """git reset failure rolls back to saved HEAD."""
        head_proc = _make_subprocess_mock(stdout=b"abc1234\n")
        reset_fail_proc = _make_subprocess_mock(
            returncode=1, stderr=b"reset failed"
        )
        rollback_reset_proc = _make_subprocess_mock(returncode=0)
        rollback_uv_proc = _make_subprocess_mock(returncode=0)
        mock_exec.side_effect = [
            head_proc,  # save HEAD (rev-parse HEAD)
            _make_subprocess_mock(returncode=0),  # git fetch ok
            reset_fail_proc,  # git reset --hard fails
            rollback_reset_proc,  # rollback: git reset --hard abc1234
            rollback_uv_proc,  # rollback: uv sync
        ]
        mgr = RealUpdateManager()
        events = []
        async for event in mgr.apply_update():
            events.append(event)
        error_events = [e for e in events if e.get("stage") == "error"]
        assert len(error_events) == 1

    @patch("app.services.update_manager.asyncio.create_subprocess_exec")
    async def test_rollback_on_sync_failure(self, mock_exec):
        """uv sync failure rolls back."""
        head_proc = _make_subprocess_mock(stdout=b"abc1234\n")
        uv_fail_proc = _make_subprocess_mock(returncode=1)
        rollback_reset_proc = _make_subprocess_mock(returncode=0)
        rollback_uv_proc = _make_subprocess_mock(returncode=0)
        mock_exec.side_effect = [
            head_proc,  # save HEAD (rev-parse HEAD)
            _make_subprocess_mock(returncode=0),  # git fetch ok
            _make_subprocess_mock(returncode=0),  # git reset ok
            uv_fail_proc,  # uv sync fails
            rollback_reset_proc,  # rollback: reset
            rollback_uv_proc,  # rollback: uv sync
        ]
        mgr = RealUpdateManager()
        events = []
        async for event in mgr.apply_update():
            events.append(event)
        error_events = [e for e in events if e.get("stage") == "error"]
        assert len(error_events) == 1

    @patch("app.services.update_manager.asyncio.create_subprocess_exec")
    async def test_rollback_on_ruff_failure(self, mock_exec):
        """ruff check failure rolls back."""
        head_proc = _make_subprocess_mock(stdout=b"abc1234\n")
        ruff_fail_proc = _make_subprocess_mock(returncode=1)
        rollback_reset_proc = _make_subprocess_mock(returncode=0)
        rollback_uv_proc = _make_subprocess_mock(returncode=0)
        mock_exec.side_effect = [
            head_proc,  # save HEAD (rev-parse HEAD)
            _make_subprocess_mock(returncode=0),  # git fetch ok
            _make_subprocess_mock(returncode=0),  # git reset ok
            _make_subprocess_mock(returncode=0),  # uv sync ok
            ruff_fail_proc,  # ruff check fails
            rollback_reset_proc,  # rollback: reset
            rollback_uv_proc,  # rollback: uv sync
        ]
        mgr = RealUpdateManager()
        events = []
        async for event in mgr.apply_update():
            events.append(event)
        error_events = [e for e in events if e.get("stage") == "error"]
        assert len(error_events) == 1

    @patch("app.services.update_manager.asyncio.create_subprocess_exec")
    async def test_concurrent_apply_blocked_by_lock(self, mock_exec):
        """Second concurrent apply_update call yields error event immediately."""
        async def slow_communicate(*args, **kwargs):
            await asyncio.sleep(0.5)
            return (b"abc1234\n", b"")

        slow_proc = AsyncMock()
        slow_proc.communicate = slow_communicate
        slow_proc.returncode = 0

        # Provide enough mocks for the first apply to complete after slow HEAD
        mock_exec.side_effect = [
            slow_proc,  # save HEAD (rev-parse HEAD) — slow, holds lock
            _make_subprocess_mock(returncode=0),  # git fetch
            _make_subprocess_mock(returncode=0),  # git reset
            _make_subprocess_mock(returncode=0),  # uv sync
            _make_subprocess_mock(returncode=0),  # ruff check
            _make_subprocess_mock(returncode=0),  # restart
        ]
        mgr = RealUpdateManager()

        # Start first apply in background
        async def collect_events():
            events = []
            async for event in mgr.apply_update():
                events.append(event)
            return events

        task1 = asyncio.create_task(collect_events())
        await asyncio.sleep(0.05)  # Let first apply acquire the lock

        # Second apply should immediately get error
        events2 = []
        async for event in mgr.apply_update():
            events2.append(event)

        assert len(events2) == 1
        assert events2[0]["stage"] == "error"
        assert events2[0]["error"] == "update_in_progress"

        # Clean up task1
        await task1


# ---------------------------------------------------------------------------
# Flag file (D-13)
# ---------------------------------------------------------------------------


class TestFlagFile:
    """RealUpdateManager writes .update-state before restart."""

    @patch("app.services.update_manager.asyncio.create_subprocess_exec")
    async def test_flag_file_written_before_restart(self, mock_exec):
        """A .update-state flag file is written with prev_hash before restart."""
        head_proc = _make_subprocess_mock(stdout=b"abc1234\n")
        mock_exec.side_effect = [
            head_proc,  # save HEAD (rev-parse HEAD)
            _make_subprocess_mock(returncode=0),  # git fetch
            _make_subprocess_mock(returncode=0),  # git reset
            _make_subprocess_mock(returncode=0),  # uv sync
            _make_subprocess_mock(returncode=0),  # ruff check
            _make_subprocess_mock(returncode=0),  # fire-and-forget restart
        ]
        mgr = RealUpdateManager()
        events = []
        async for event in mgr.apply_update():
            events.append(event)
        # The last event is restarting, meaning flag file was written
        assert events[-1]["stage"] == "restarting"
        # Verify the flag file was created
        flag_path = mgr._repo_dir / ".update-state"
        assert flag_path.exists()
        data = json.loads(flag_path.read_text())
        assert data["state"] == "pending"
        assert data["prev_hash"] == "abc1234"
        # Cleanup
        flag_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# get_version
# ---------------------------------------------------------------------------


class TestGetVersion:
    """RealUpdateManager.get_version() returns git describe output."""

    @patch("app.services.update_manager.asyncio.create_subprocess_exec")
    async def test_get_version_returns_version_and_commit(self, mock_exec):
        describe_proc = _make_subprocess_mock(
            stdout=b"v1.4.0-12-gabc1234\n"
        )
        short_proc = _make_subprocess_mock(stdout=b"abc1234\n")
        mock_exec.side_effect = [describe_proc, short_proc]
        mgr = RealUpdateManager()
        result = await mgr.get_version()
        assert result["version"] == "v1.4.0-12-gabc1234"
        assert result["commit"] == "abc1234"


# ---------------------------------------------------------------------------
# MockUpdateManager
# ---------------------------------------------------------------------------


class TestMockUpdateManager:
    """MockUpdateManager returns fake data for testing."""

    def test_is_mock_true(self):
        mgr = MockUpdateManager()
        assert mgr.is_mock is True

    async def test_check_update_returns_no_update(self):
        mgr = MockUpdateManager()
        result = await mgr.check_update()
        assert result["update_available"] is False
        assert result["local_commit"] == "mock123"
        assert result["remote_commit"] == "mock123"

    async def test_apply_update_yields_mock_events(self):
        mgr = MockUpdateManager()
        events = []
        async for event in mgr.apply_update():
            events.append(event)
        assert len(events) > 0

    async def test_get_version_returns_mock(self):
        mgr = MockUpdateManager()
        result = await mgr.get_version()
        assert result["version"] == "mock-v0.0.0"
        assert result["commit"] == "mock123"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestFactory:
    """create_update_manager() returns Real or Mock based on git availability."""

    @patch("app.services.update_manager.shutil.which", return_value="/usr/bin/git")
    def test_factory_returns_real_when_git_available(self, mock_which):
        mgr = create_update_manager()
        assert isinstance(mgr, RealUpdateManager)
        assert mgr.is_mock is False

    @patch("app.services.update_manager.shutil.which", return_value=None)
    def test_factory_returns_mock_when_git_missing(self, mock_which):
        mgr = create_update_manager()
        assert isinstance(mgr, MockUpdateManager)
        assert mgr.is_mock is True

    @patch("app.services.update_manager.shutil.which", return_value=None)
    def test_factory_creates_new_instance_each_call(self, mock_which):
        mgr1 = create_update_manager()
        mgr2 = create_update_manager()
        assert mgr1 is not mgr2


# ---------------------------------------------------------------------------
# Base class contract
# ---------------------------------------------------------------------------


class TestUpdateManagerBaseClass:
    """UpdateManager base class defines interface and raises NotImplementedError."""

    def test_base_class_is_mock_false(self):
        mgr = UpdateManager()
        assert mgr.is_mock is False

    async def test_base_check_update_raises(self):
        mgr = UpdateManager()
        with pytest.raises(NotImplementedError):
            await mgr.check_update()

    async def test_base_apply_update_raises(self):
        mgr = UpdateManager()
        with pytest.raises(NotImplementedError):
            # apply_update is async generator, need to iterate
            async for _ in mgr.apply_update():
                pass

    async def test_base_get_version_raises(self):
        mgr = UpdateManager()
        with pytest.raises(NotImplementedError):
            await mgr.get_version()


# ---------------------------------------------------------------------------
# uv binary resolution (regression: systemd PATH lacks ~/.local/bin)
# ---------------------------------------------------------------------------


class TestFindUv:
    """_find_uv locates the uv binary despite the restricted systemd PATH."""

    @patch("app.services.update_manager.shutil.which", return_value="/custom/uv")
    def test_uses_which_when_available(self, mock_which):
        assert _find_uv() == "/custom/uv"

    @patch("app.services.update_manager.shutil.which", return_value=None)
    def test_falls_back_to_local_bin(self, mock_which, tmp_path, monkeypatch):
        """When uv is not on PATH, resolve ~/.local/bin/uv (install.sh location)."""
        local_uv = tmp_path / ".local" / "bin" / "uv"
        local_uv.parent.mkdir(parents=True)
        local_uv.write_text("")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        assert _find_uv() == str(local_uv)


class TestRunUvMissingBinary:
    """_run_uv degrades gracefully when the uv binary cannot be spawned."""

    @patch("app.services.update_manager.asyncio.create_subprocess_exec")
    async def test_returns_nonzero_instead_of_raising(self, mock_exec):
        mock_exec.side_effect = FileNotFoundError("no such file: uv")
        rc = await _run_uv("sync")
        assert rc != 0

    @patch("app.services.update_manager.asyncio.create_subprocess_exec")
    async def test_apply_emits_error_event_when_uv_missing(self, mock_exec):
        """Missing uv at the sync stage yields a clean error event, not a crash."""
        mock_exec.side_effect = [
            _make_subprocess_mock(stdout=b"abc1234\n"),  # rev-parse HEAD
            _make_subprocess_mock(returncode=0),  # git fetch
            _make_subprocess_mock(returncode=0),  # git reset
            FileNotFoundError("no such file: uv"),  # uv sync
            _make_subprocess_mock(returncode=0),  # rollback: git reset
            FileNotFoundError("no such file: uv"),  # rollback: uv sync
        ]
        mgr = RealUpdateManager()
        events = []
        async for event in mgr.apply_update():
            events.append(event)
        error_events = [e for e in events if e.get("stage") == "error"]
        assert len(error_events) == 1
        assert "syncing" in [e["stage"] for e in events]
