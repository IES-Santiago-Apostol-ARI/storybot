"""Update manager service — wraps git/uv/ruff subprocess calls for OTA updates."""

import asyncio
import json
import os
import platform
import shutil
import sys
from pathlib import Path

# Where the Jetson's system apt packages live (python3-jetson-gpio). Module
# level so tests can point it at a fixture directory.
_SYSTEM_DIST_PACKAGES = Path("/usr/lib/python3/dist-packages")


async def _run_git(*args: str, cwd: Path | None = None) -> tuple[str, str, int]:
    """Run git command and return (stdout, stderr, returncode).

    ``cwd`` defaults to None (current directory). When set, git runs in that
    directory — critical for safety since ``git reset --hard`` in the wrong
    directory would be destructive.
    """
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    stdout, stderr = await proc.communicate()
    return (
        stdout.decode().strip(),
        stderr.decode().strip(),
        proc.returncode if proc.returncode is not None else -1,
    )


def _find_uv() -> str:
    """Locate the uv binary, accounting for systemd's restricted PATH.

    Under systemd (storybot.service) PATH does not include ~/.local/bin, where
    deploy/install.sh installs uv, so shutil.which("uv") returns None there.
    Fall back to the known install locations before giving up.
    """
    uv_bin = shutil.which("uv")
    if uv_bin:
        return uv_bin
    candidates = [
        Path.home() / ".local" / "bin" / "uv",  # install.sh location
        Path(sys.prefix) / "bin" / "uv",  # .venv/bin/uv, if installed there
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    # Nothing found: return the most likely path so the caller's spawn raises a
    # clear FileNotFoundError, which _run_uv turns into a non-zero return code.
    return str(candidates[0])


async def _run_uv(*args: str, cwd: Path | None = None) -> int:
    """Run uv command and return returncode only.

    Returns a non-zero code (rather than raising) when the uv binary cannot be
    spawned, so apply_update can emit a clean error event instead of crashing
    the SSE stream mid-transfer. ``cwd`` pins where uv resolves pyproject.toml,
    so sync never targets the wrong project.
    """
    uv_bin = _find_uv()
    try:
        proc = await asyncio.create_subprocess_exec(
            uv_bin,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
    except FileNotFoundError:
        _log_event("uv_not_found", uv_bin=uv_bin)
        return -1
    await proc.communicate()
    return proc.returncode if proc.returncode is not None else -1


def _find_ruff() -> str:
    """Locate the ruff binary, accounting for systemd's restricted PATH.

    Under systemd (storybot.service) PATH does not include ~/.local/bin, where
    ruff is installed, so shutil.which("ruff") returns None there.
    Fall back to the known install locations before giving up.
    """
    ruff_bin = shutil.which("ruff")
    if ruff_bin:
        return ruff_bin
    candidates = [
        Path.home() / ".local" / "bin" / "ruff",  # install.sh location
        Path(sys.prefix) / "bin" / "ruff",  # .venv/bin/ruff, if installed there
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    # Nothing found: return the most likely path so the caller's spawn raises a
    # clear FileNotFoundError, which _run_ruff turns into a non-zero return code.
    return str(candidates[0])


async def _run_ruff(cwd: Path | None = None) -> int:
    """Run ruff check app/ and return returncode only.

    Returns a non-zero code (rather than raising) when the ruff binary cannot be
    spawned, so apply_update can emit a clean error event instead of crashing
    the SSE stream mid-transfer.
    """
    ruff_bin = _find_ruff()
    try:
        proc = await asyncio.create_subprocess_exec(
            ruff_bin,
            "check",
            "app/",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
    except FileNotFoundError:
        _log_event("ruff_not_found", ruff_bin=ruff_bin)
        return -1
    await proc.communicate()
    return proc.returncode if proc.returncode is not None else -1


def _relink_jetson_gpio(repo_dir: Path) -> None:
    """Restore the system Jetson.GPIO symlink that ``uv sync`` prunes.

    On the Jetson, Jetson.GPIO ships as a system apt package and is symlinked
    into the venv by deploy/install.sh. It lives in the ``jetson`` extra, which
    aarch64 deliberately skips, so the plain ``uv sync`` an update runs
    uninstalls it — after which gpio_handler silently falls back to the Mock
    and the physical buttons stop working. Re-link after every sync.
    """
    if platform.machine() != "aarch64":
        return
    site_dirs = sorted((repo_dir / ".venv" / "lib").glob("python3*/site-packages"))
    if not site_dirs:
        return
    site_packages = site_dirs[0]
    system_pkg = _SYSTEM_DIST_PACKAGES / "Jetson"
    if not system_pkg.is_dir():
        _log_event("jetson_gpio_relink_skipped", reason="system_package_missing")
        return
    targets = [
        system_pkg,
        *sorted(_SYSTEM_DIST_PACKAGES.glob("Jetson.GPIO-*.egg-info")),
    ]
    for target in targets:
        link = site_packages / target.name
        try:
            if link.is_symlink() or link.exists():
                link.unlink()
            link.symlink_to(target)
        except OSError as e:
            _log_event(
                "jetson_gpio_relink_failed",
                target=str(target),
                reason=type(e).__name__,
            )
            return
    _log_event("jetson_gpio_relinked", site_packages=str(site_packages))


def _log_event(event: str, **kwargs: object) -> None:
    """Structured JSON log to stderr (same pattern as wifi_manager)."""
    print(
        json.dumps({"event": event, **kwargs}),
        file=sys.stderr,
    )


class UpdateManager:
    """Base contract for update management operations."""

    is_mock: bool = False

    async def check_update(self) -> dict:
        raise NotImplementedError

    async def apply_update(self):
        raise NotImplementedError
        yield  # makes this an async generator

    async def get_version(self) -> dict:
        raise NotImplementedError


class RealUpdateManager(UpdateManager):
    """Real update manager wrapping git/uv/ruff subprocess calls."""

    is_mock: bool = False

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._repo_dir: Path = Path(__file__).resolve().parent.parent.parent

    async def check_update(self) -> dict:
        """Check if an update is available by comparing local and remote HEAD."""
        _, fetch_stderr, fetch_rc = await _run_git(
            "fetch", "origin", "--quiet", cwd=self._repo_dir
        )
        if fetch_rc != 0:
            return {
                "update_available": False,
                "local_commit": "",
                "remote_commit": "",
                "error": f"fetch failed: {fetch_stderr}",
            }
        local_stdout, _, _ = await _run_git("rev-parse", "HEAD", cwd=self._repo_dir)
        remote_stdout, _, _ = await _run_git(
            "rev-parse", "origin/main", cwd=self._repo_dir
        )
        return {
            "update_available": local_stdout != remote_stdout,
            "local_commit": local_stdout,
            "remote_commit": remote_stdout,
        }

    async def apply_update(self):
        """Apply update by fetching, resetting, syncing, checking, restarting.

        Yields SSE progress events. Rolls back on any failure.
        """
        # Concurrent guard (T-23-02)
        if self._lock.locked():
            yield {"stage": "error", "error": "update_in_progress"}
            return

        async with self._lock:
            # Save current HEAD for rollback (D-01)
            local_stdout, _, _ = await _run_git("rev-parse", "HEAD", cwd=self._repo_dir)
            prev_hash = local_stdout

            # Stage 1: Fetching
            yield {"stage": "fetching", "done": False}
            _, fetch_stderr, fetch_rc = await _run_git(
                "fetch", "origin", "--quiet", cwd=self._repo_dir
            )
            if fetch_rc != 0:
                yield {
                    "stage": "error",
                    "error": f"fetch failed: {fetch_stderr}",
                }
                return

            # Stage 2: Updating (git reset)
            yield {"stage": "updating", "done": False}
            _, reset_stderr, reset_rc = await _run_git(
                "reset", "--hard", "origin/main", cwd=self._repo_dir
            )
            if reset_rc != 0:
                await self._rollback(prev_hash)
                yield {
                    "stage": "error",
                    "error": f"reset failed: {reset_stderr}",
                }
                return

            # Stage 3: Syncing (uv sync)
            yield {"stage": "syncing", "done": False}
            sync_rc = await _run_uv("sync", cwd=self._repo_dir)
            if sync_rc != 0:
                await self._rollback(prev_hash)
                yield {
                    "stage": "error",
                    "error": f"uv sync failed (rc={sync_rc})",
                }
                return
            _relink_jetson_gpio(self._repo_dir)

            # Stage 4: Checking (ruff check)
            yield {"stage": "checking", "done": False}
            ruff_rc = await _run_ruff(cwd=self._repo_dir)
            if ruff_rc != 0:
                await self._rollback(prev_hash)
                yield {
                    "stage": "error",
                    "error": f"ruff check failed (rc={ruff_rc})",
                }
                return

            # Write flag file (D-13)
            self._write_update_flag(prev_hash)

            # Stage 5: Restarting
            yield {"stage": "restarting", "done": True}

            # Fire-and-forget restart (D-08, D-09)
            await self._trigger_restart()

    async def _rollback(self, prev_hash: str) -> None:
        """Roll back to previous commit and sync dependencies (D-01, D-02)."""
        await _run_git("reset", "--hard", prev_hash, cwd=self._repo_dir)
        await _run_uv("sync", cwd=self._repo_dir)
        _relink_jetson_gpio(self._repo_dir)
        _log_event("update_rolled_back", prev_hash=prev_hash)

    def _write_update_flag(self, prev_hash: str) -> None:
        """Write .update-state flag file before restart (D-13)."""
        flag_path = self._repo_dir / ".update-state"
        flag_path.write_text(json.dumps({"state": "pending", "prev_hash": prev_hash}))

    async def _trigger_restart(self) -> None:
        """Fire-and-forget restart with start_new_session=True."""
        await asyncio.create_subprocess_exec(
            "bash",
            "-c",
            "sleep 2 && sudo systemctl restart storybot",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )

    async def get_version(self) -> dict:
        """Return current version info from git."""
        describe_stdout, _, _ = await _run_git(
            "describe", "--always", "--dirty", cwd=self._repo_dir
        )
        short_stdout, _, _ = await _run_git(
            "rev-parse", "--short", "HEAD", cwd=self._repo_dir
        )
        return {"version": describe_stdout, "commit": short_stdout}


class MockUpdateManager(UpdateManager):
    """Mock update manager for testing without git."""

    is_mock: bool = True

    async def check_update(self) -> dict:
        return {
            "update_available": False,
            "local_commit": "mock123",
            "remote_commit": "mock123",
        }

    async def apply_update(self):
        """Yield mock progress events."""
        for stage in ["fetching", "updating", "syncing", "checking", "restarting"]:
            yield {
                "stage": stage,
                "done": stage == "restarting",
            }

    async def get_version(self) -> dict:
        return {"version": "mock-v0.0.0", "commit": "mock123"}


# Module-level singleton for RealUpdateManager.
# The asyncio.Lock must be shared across all requests to actually guard
# concurrent POST /api/updates/apply. Each request getting its own lock
# (the old create_update_manager behavior) makes the guard a no-op.
_real_update_manager_instance: RealUpdateManager | None = None


def _get_real_update_manager() -> RealUpdateManager:
    """Return the shared RealUpdateManager singleton."""
    global _real_update_manager_instance
    if _real_update_manager_instance is None:
        _real_update_manager_instance = RealUpdateManager()
    return _real_update_manager_instance


def create_update_manager() -> UpdateManager:
    """Create appropriate update manager based on git availability.

    Returns:
        - MockUpdateManager when ``TESTING`` env is set (mirrors
          create_bt_manager) — prevents tests that exercise the real
          ``/api/updates/apply`` endpoint from running destructive
          ``git reset --hard`` against the working repo.
        - RealUpdateManager singleton if git is available (shared instance
          ensures the asyncio.Lock guards concurrent applies).
        - MockUpdateManager otherwise.
    """
    if os.environ.get("TESTING"):
        return MockUpdateManager()
    if shutil.which("git"):
        return _get_real_update_manager()
    return MockUpdateManager()
