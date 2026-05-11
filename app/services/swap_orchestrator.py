"""Swap orchestrator — manages llama↔SD lifecycle for cover generation."""

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

# Constants
SD_VENV_PYTHON = Path("/home/ari/sd-cover/.venv/bin/python")
SD_WORKER = (
    Path(__file__).resolve().parent.parent.parent
    / "scripts"
    / "sd_cover_worker.py"
)
MEM_SETTLE_S = 3
LLAMA_TIMEOUT_S = 30
LLAMA_HEALTH_URL = "http://127.0.0.1:8080/v1/models"


class LlamaRelaunchError(Exception):
    """Raised when llama-server cannot be relaunched after cover generation."""


async def _wait_for_llama_health(timeout_s: float) -> bool:
    """Poll /v1/models until 200 or timeout."""
    deadline = time.monotonic() + timeout_s
    async with httpx.AsyncClient() as client:
        while time.monotonic() < deadline:
            try:
                resp = await client.get(LLAMA_HEALTH_URL, timeout=5.0)
                if resp.status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1.0)
    return False


class SwapOrchestrator:
    """Orchestrates the llama↔SD swap cycle for cover generation."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def generate_cover_for_story(
        self, story_id: str, positive: str, negative: str, seed: int
    ) -> tuple[Path | None, Path | None, float | None]:
        """Run the full swap cycle: stop llama, generate cover, restart llama.

        Returns (preview_path, print_path, gen_seconds) on success,
        (None, None, None) on failure or busy-lock.
        """
        if self._lock.locked():
            print(
                json.dumps(
                    {"event": "cover_dropped_busy", "story_id": story_id}
                ),
                file=sys.stderr,
            )
            return (None, None, None)

        async with self._lock:
            try:
                return await self._run_swap(story_id, positive, negative, seed)
            except LlamaRelaunchError:
                raise
            except Exception as e:
                print(
                    json.dumps(
                        {
                            "event": "cover_failed",
                            "story_id": story_id,
                            "reason": type(e).__name__,
                            "detail": str(e),
                        }
                    ),
                    file=sys.stderr,
                )
                return (None, None, None)

    async def _run_swap(
        self, story_id: str, positive: str, negative: str, seed: int
    ) -> tuple[Path | None, Path | None, float | None]:
        # 1. Stop llama-server and let the kernel settle
        stop_proc = await asyncio.create_subprocess_exec(
            "sudo", "systemctl", "stop", "llama-server",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await stop_proc.wait()

        # 2. Brief settle delay — swap-in pressure makes MemAvailable unreliable
        # as a gate, so we trust sequential CPU offload in the worker.
        await asyncio.sleep(MEM_SETTLE_S)

        # 3. Spawn SD worker
        payload = json.dumps(
            {
                "positive_prompt": positive,
                "negative_prompt": negative,
                "seed": seed,
                "out_dir": str(Path("content/generated") / story_id),
            }
        )
        worker = await asyncio.create_subprocess_exec(
            str(SD_VENV_PYTHON),
            str(SD_WORKER),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_data, stderr_data = await worker.communicate(
            input=payload.encode()
        )

        # 4. Always restart llama-server
        start_proc = await asyncio.create_subprocess_exec(
            "sudo", "systemctl", "start", "llama-server",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await start_proc.wait()

        # 5. Verify llama is back
        healthy = await _wait_for_llama_health(LLAMA_TIMEOUT_S)
        if not healthy:
            msg = json.dumps(
                {
                    "event": "llama_relaunch_failed",
                    "story_id": story_id,
                    "reason": "health_check_timeout",
                    "detail": (
                        f"/v1/models not 200 within {LLAMA_TIMEOUT_S}s"
                    ),
                }
            )
            print(msg, file=sys.stderr)
            raise LlamaRelaunchError(
                f"llama-server health check failed after {LLAMA_TIMEOUT_S}s"
            )

        # 6. Process worker result
        if worker.returncode != 0:
            reason = stderr_data.decode().strip() if stderr_data else "unknown"
            print(
                json.dumps(
                    {
                        "event": "cover_failed",
                        "story_id": story_id,
                        "reason": "worker_nonzero_exit",
                        "detail": reason,
                    }
                ),
                file=sys.stderr,
            )
            return (None, None, None)

        try:
            result = json.loads(stdout_data.decode())
            return (
                Path(result["preview"]),
                Path(result["print"]),
                result["gen_seconds"],
            )
        except (json.JSONDecodeError, KeyError) as e:
            print(
                json.dumps(
                    {
                        "event": "cover_failed",
                        "story_id": story_id,
                        "reason": "bad_worker_output",
                        "detail": str(e),
                    }
                ),
                file=sys.stderr,
            )
            return (None, None, None)
