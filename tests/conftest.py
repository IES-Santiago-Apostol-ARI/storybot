"""Pytest configuration and fixtures."""

import os
import tempfile
from pathlib import Path

import pytest

# Set testing environment variable before app imports
# This prevents the app lifespan from creating real content/stories directories
os.environ["TESTING"] = "1"


@pytest.fixture
def temp_config_file():
    """Create a temporary config file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write('{"led_brightness": 255, "audio_volume": 1.0}')
        temp_path = f.name
    yield Path(temp_path)
    # Cleanup
    Path(temp_path).unlink(missing_ok=True)


# --- Phase 28 (boot-reconnect-resilience) shared Wave-0 fixtures ---
# Hardware-free infrastructure: a mutable monotonic clock, an await-able fake
# sleep that records its delays, a pre-seeded MockBtManager, and a stubbed
# audio route. Together these let the boot-reconnect / health-monitor / fallback
# behaviors (Plans 01-04) be asserted deterministically with no dbus, no pactl,
# and no wall-clock waits (TEST-BT-04).


class _FakeClock:
    """Mutable monotonic-time source.

    ``now`` advances ONLY when ``fake_sleep`` is awaited — never on its own —
    so backoff schedules and the ≤5-min budget clamp (BOOT-03/D-11) are exact.
    Also callable so it can be injected directly as a ``now=`` seam.
    """

    def __init__(self) -> None:
        self.now: float = 0.0

    def __call__(self) -> float:
        return self.now


class _FakeSleep:
    """Await-able fake ``asyncio.sleep`` bound to a ``_FakeClock``.

    Awaiting ``fake_sleep(delay)`` records ``delay`` in ``.delays`` and advances
    the bound clock by ``delay`` — with no real wait. Exposes ``.delays`` so
    tests assert the backoff schedule (1, 2, 4, 8, …) and the total-budget
    clamp (sum ≤ 300, BOOT-03/D-11, Pitfall 6).
    """

    def __init__(self, clock: _FakeClock) -> None:
        self._clock = clock
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        self._clock.now += delay


@pytest.fixture
def fake_clock() -> _FakeClock:
    """A mutable monotonic clock starting at 0.0 that only moves on fake_sleep."""
    return _FakeClock()


@pytest.fixture
def fake_sleep(fake_clock: _FakeClock) -> _FakeSleep:
    """An await-able fake sleep recording delays into ``.delays``.

    Bound to the per-test ``fake_clock``: awaiting it advances
    ``fake_clock.now`` by the awaited delay, with no real sleeping.
    """
    return _FakeSleep(fake_clock)


@pytest.fixture
def mock_bt_manager():
    """A fresh ``MockBtManager`` pre-seeded with one paired "Mock JBL" speaker.

    Gives the reconnect target with no pairing step (TEST-BT-04). Imported
    lazily so the fixture is robust to import-order differences across suites.
    """
    from app.services.bt_manager import MockBtManager

    return MockBtManager()


class _StubRoute:
    """Stubbed audio router recording calls; per-method configurable success.

    Exposes await-able ``route_to_bt(mac)`` and ``route_to_wired()`` that
    record their calls in ``.bt_calls`` / ``.wired_calls`` and return a
    configurable ``bool`` (default True). Lets tests assert AUDIO-05 fallback
    ("route_to_wired called") and re-route-back without invoking pactl.
    """

    def __init__(self) -> None:
        self.bt_calls: list[str] = []
        self.wired_calls: list[None] = []
        self.bt_ok: bool = True
        self.wired_ok: bool = True

    async def route_to_bt(self, mac: str) -> bool:
        self.bt_calls.append(mac)
        return self.bt_ok

    async def route_to_wired(self) -> bool:
        self.wired_calls.append(None)
        return self.wired_ok


@pytest.fixture
def stub_route() -> _StubRoute:
    """A stubbed audio router (no pactl) recording bt/wired route calls."""
    return _StubRoute()
