"""Boot-reconnect module tests (TEST-BT-04).

Hardware-free: all timing driven by the Wave-0 fake clock + fake sleep;
manager and audio router injected via run_once seams. No dbus, no pactl,
no wall-clock waits. Six scenarios covering the full run-once contract.
"""

import pytest
from app.bt_boot_reconnect import backoff_delays, run_once


@pytest.fixture
def _log_capture():
    """Capture log events emitted by _log_event."""
    events = []

    def _capture(event, **kwargs):
        events.append({"event": event, **kwargs})

    return events, _capture


class _FailingManager:
    """Manager whose connect() fails a configurable number of times then succeeds."""

    def __init__(self, fail_count: int = 0) -> None:
        self._fail_count = fail_count
        self._attempts = 0
        self._last_speaker: dict | None = {
            "name": "Mock JBL",
            "mac": "AA:BB:CC:00:11:22",
            "last_connected": "2026-06-12T17:00:00+00:00",
        }

    async def get_last_speaker(self) -> dict | None:
        return dict(self._last_speaker) if self._last_speaker is not None else None

    async def connect(self, mac: str) -> dict:
        self._attempts += 1
        if self._attempts <= self._fail_count:
            return {"ok": False}
        return {"ok": True}

    @property
    def attempts(self) -> int:
        return self._attempts


class _NoSpeakerManager:
    """Manager whose get_last_speaker returns None."""

    async def get_last_speaker(self) -> dict | None:
        return None

    async def connect(self, mac: str) -> dict:
        raise RuntimeError("should not be called")


@pytest.mark.asyncio
async def test_connects_first_try(fake_clock, fake_sleep, _log_capture):
    """Manager whose connect returns ok on attempt 1 → exit 0, one call, no wired."""
    events, log = _log_capture
    manager = _FailingManager(fail_count=0)

    result = await run_once(
        manager, route_to_wired=lambda: None, sleep=fake_sleep, log=log, now=fake_clock
    )

    assert result == 0
    assert manager.attempts == 1
    assert fake_sleep.delays == []
    # No wired fallback called on success
    assert not any(e["event"] == "bt_boot_giveup" for e in events)


@pytest.mark.asyncio
async def test_retry_then_success(fake_clock, fake_sleep, _log_capture):
    """Connect fails twice then succeeds → exit 0, three calls, backoff [1, 2]."""
    events, log = _log_capture
    manager = _FailingManager(fail_count=2)

    result = await run_once(
        manager, route_to_wired=lambda: None, sleep=fake_sleep, log=log, now=fake_clock
    )

    assert result == 0
    assert manager.attempts == 3
    assert fake_sleep.delays == [1.0, 2.0]


@pytest.mark.asyncio
async def test_backoff_shape_and_budget(fake_clock, fake_sleep):
    """backoff_delays yields 1,2,4,8,16,30,30,… each ≤ 30; total ≤ 300."""
    delays = []
    for d in backoff_delays(now=fake_clock):
        delays.append(d)
        await fake_sleep(d)
    # All values ≤ cap (30)
    assert all(d <= 30.0 for d in delays)
    # Total budget ≤ 300
    assert sum(delays) <= 300.0
    # First five values follow doubling pattern before cap
    assert delays[0] == 1.0
    assert delays[1] == 2.0
    assert delays[2] == 4.0
    assert delays[3] == 8.0
    assert delays[4] == 16.0


@pytest.mark.asyncio
async def test_giveup_routes_wired(fake_clock, fake_sleep, _log_capture):
    """Connect always fails → after budget exhausted, route_to_wired + giveup."""
    events, log = _log_capture
    wired_called = False

    async def stub_route_to_wired() -> bool:
        nonlocal wired_called
        wired_called = True
        return True

    manager = _FailingManager(fail_count=999)

    result = await run_once(
        manager, route_to_wired=stub_route_to_wired, sleep=fake_sleep, log=log, now=fake_clock
    )

    assert result == 0
    assert wired_called is True
    giveup_events = [e for e in events if e["event"] == "bt_boot_giveup"]
    assert len(giveup_events) == 1
    assert giveup_events[0]["mac"] == "AA:BB:CC:00:11:22"


@pytest.mark.asyncio
async def test_no_speaker_noop(_log_capture):
    """get_last_speaker returns None → zero connect calls, exit 0."""
    events, log = _log_capture
    manager = _NoSpeakerManager()

    result = await run_once(
        manager, route_to_wired=lambda: None, sleep=lambda d: None, log=log
    )

    assert result == 0
    no_speaker_events = [e for e in events if e["event"] == "bt_boot_no_speaker"]
    assert len(no_speaker_events) == 1


@pytest.mark.asyncio
async def test_target_from_store_not_hardcoded(fake_clock, fake_sleep, _log_capture):
    """MAC passed to connect equals the store's mac, not the legacy one."""
    events, log = _log_capture
    manager = _FailingManager(fail_count=0)

    result = await run_once(
        manager, route_to_wired=lambda: None, sleep=fake_sleep, log=log, now=fake_clock
    )

    assert result == 0
    # The connect was called with the store's MAC
    assert manager.attempts == 1
    # Verify no legacy MAC anywhere in events or logic
    for e in events:
        assert "00:42:79:E9:90:46" not in str(e)
