"""Boot-reconnect module — standalone, run-once-then-exit (D-01/D-03).

Reads the remembered speaker from the device store, attempts connect over an
exponential backoff bounded to ≤ 5 minutes (BOOT-03/D-11), and on give-up
ensures wired audio + logs the give-up event (D-12). Reuses the already-shipped
RealBtManager.connect() which internally calls bt_audio.route_to_bt() for
A2DP activation — no BlueZ or pactl logic reimplemented here.

Importable without dbus-fast at top level (lazy via the manager seam only).
"""

import asyncio
import json
import sys
import time
from collections.abc import Callable

from app.services import bt_audio
from app.services.bt_manager import create_bt_manager


def _log_event(event: str, **kwargs: object) -> None:
    """Structured JSON log to stderr (same shape as bt_manager)."""
    print(
        json.dumps({"event": event, **kwargs}),
        file=sys.stderr,
    )


def backoff_delays(
    start: float = 1.0,
    cap: float = 30.0,
    budget: float = 300.0,
    now: Callable[[], float] = time.monotonic,
):
    """Yield sleep durations with monotonic-deadline clamp (BOOT-03/D-11).

    Produces: start, start*2, start*4, … capped at `cap`, never overshooting
    the total `budget`. The final yielded value is clamped so it never crosses
    the deadline.

    Args:
        start: Initial delay in seconds.
        cap: Maximum per-iteration delay (30 s).
        budget: Total time budget in seconds (300 = 5 min).
        now: Monotonic clock callable (injectable for testing).

    Yields:
        Float sleep durations, each ≤ cap and never exceeding the remaining
        time until the deadline.
    """
    deadline = now() + budget
    delay = start
    while True:
        remaining = deadline - now()
        if remaining <= 0:
            return
        yield min(delay, cap, remaining)
        delay *= 2


async def run_once(
    manager,
    route_to_wired,
    sleep,
    *,
    log=_log_event,
    now=time.monotonic,
):
    """Run the boot reconnect once then exit (D-01/D-03).

    Reads the remembered speaker from the manager's device store. If a speaker
    is found, attempts connect with exponential backoff. On success returns 0.
    On budget exhaustion routes to wired and logs give-up. If no speaker is
    remembered, logs and returns 0 immediately (D-13 stop condition).

    Args:
        manager: BtManager instance with get_last_speaker() and connect().
        route_to_wired: Async callable for wired audio fallback (AUDIO-02).
        sleep: Async sleep callable (asyncio.sleep or fake for testing).
        log: Structured logging function.
        now: Monotonic clock callable (injectable for testing).

    Returns:
        Always 0 (success — the script itself is the unit of success/failure).
    """
    target = await manager.get_last_speaker()
    if not target:
        log("bt_boot_no_speaker")
        return 0

    for delay in backoff_delays(now=now):
        try:
            res = await manager.connect(target["mac"])
        except Exception as exc:
            # Defensive guard — manager methods return dicts, but catch escapes.
            log("bt_boot_connect_error", error=type(exc).__name__)
            res = {"ok": False}

        if res.get("ok"):
            log("bt_boot_connected", mac=target["mac"])
            return 0

        await sleep(delay)

    # Budget exhausted — give up and fall back to wired audio (D-12).
    await route_to_wired()
    log("bt_boot_giveup", mac=target["mac"])
    return 0


async def main():
    """Entry point for systemd ExecStart: ``python -m app.bt_boot_reconnect``."""
    manager = create_bt_manager()
    exit_code = await run_once(
        manager,
        bt_audio.route_to_wired,
        asyncio.sleep,
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
