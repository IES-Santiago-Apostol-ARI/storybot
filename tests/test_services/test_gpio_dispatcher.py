"""Tests for GpioDispatcher service and the poweroff endpoint.

Verifies the four button-name actions wired by Phase 36 against the deterministic
seams (no hardware):

- debounce (D-02/BTN-07): exactly one dispatch per press within gpio_debounce_ms
- power (BTN-01/D-03): delegates to system_control.poweroff()
- interrupt (BTN-02/D-05): audio stop + clear PlaybackState + {type:interrupt}
- animation (BTN-05/D-11): LedAnimator.rainbow() one-shot
- lifespan (D-01): dispatcher task created on startup, cancelled cleanly
- image: print content/last-cover, drop-on-busy, rainbow ack / error blink
- POST /api/system/poweroff shares the poweroff helper (BTN-06/D-04)
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.event_hub import EventHub
from app.services.led_animator import Mode


def _dispatcher(**kwargs):
    """Construct a GpioDispatcher with fresh in/out queues + the given seams."""
    from app.services import gpio_dispatcher

    kwargs.setdefault("gpio_events", asyncio.Queue())
    kwargs.setdefault("kiosk_events", asyncio.Queue())
    return gpio_dispatcher.GpioDispatcher(**kwargs)


def _holder(snapshot):
    """A minimal PlaybackState holder exposing a mutable .playback attribute."""
    return SimpleNamespace(playback=snapshot)


async def _drain_tasks():
    """Let pending background asyncio tasks (image generation) run to completion."""
    for _ in range(8):
        await asyncio.sleep(0)


class TestDebounce:
    """D-02/BTN-07: exactly one dispatch per press within gpio_debounce_ms."""

    @pytest.mark.asyncio
    async def test_debounce_drops_rapid_retrigger(self, fake_clock):
        from app.services import system_control

        poweroff = AsyncMock()
        d = _dispatcher(now=fake_clock)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(system_control, "poweroff", poweroff)
            await d._handle_event("power")
            await d._handle_event("power")  # immediate re-fire → debounced

        assert poweroff.await_count == 1

    @pytest.mark.asyncio
    async def test_debounce_resets_after_window(self, fake_clock):
        from app.services import system_control

        poweroff = AsyncMock()
        d = _dispatcher(now=fake_clock)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(system_control, "poweroff", poweroff)
            await d._handle_event("power")
            fake_clock.now += 1.0  # advance well past 50ms
            await d._handle_event("power")

        assert poweroff.await_count == 2


class TestPowerHandler:
    """BTN-01/D-03: power button delegates to system_control.poweroff()."""

    @pytest.mark.asyncio
    async def test_power_calls_poweroff_once(self):
        from app.services import system_control

        poweroff = AsyncMock()
        d = _dispatcher()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(system_control, "poweroff", poweroff)
            await d._handle_event("power")

        poweroff.assert_awaited_once()


class TestInterruptHandler:
    """BTN-02/D-05: stop audio, clear PlaybackState, enqueue {type:interrupt}."""

    @pytest.mark.asyncio
    async def test_interrupt_stops_audio_clears_state_enqueues(self):
        audio = MagicMock()
        audio.stop = AsyncMock()
        kiosk: asyncio.Queue = asyncio.Queue()
        holder = _holder({"story_id": "s1", "params": [], "title": "T"})

        d = _dispatcher(kiosk_events=kiosk, audio_player=audio, playback_holder=holder)

        await d._handle_event("interrupt")

        audio.stop.assert_awaited_once()
        assert holder.playback is None
        assert kiosk.get_nowait() == {"type": "interrupt"}


class TestAnimationHandler:
    """BTN-05/D-11: animation button fires LedAnimator.rainbow() one-shot."""

    @pytest.mark.asyncio
    async def test_animation_fires_rainbow(self):
        led = MagicMock()
        d = _dispatcher(led_animator=led)

        await d._handle_event("animation")

        led.rainbow.assert_called_once()

    @pytest.mark.asyncio
    async def test_power_does_not_fire_rainbow(self):
        from app.services import system_control

        led = MagicMock()
        d = _dispatcher(led_animator=led)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(system_control, "poweroff", AsyncMock())
            await d._handle_event("power")

        led.rainbow.assert_not_called()


class TestLifespan:
    """D-01: dispatcher task created on startup, cancelled cleanly on shutdown."""

    def test_lifespan_dispatcher_task_and_queues(self):
        with TestClient(app) as client:  # noqa: F841 — context runs lifespan
            task = app.state.gpio_dispatcher_task
            assert task is not None
            assert not task.done()
            assert isinstance(app.state.kiosk_events, EventHub)
            assert app.state.kiosk_events is not app.state.gpio_events
            assert hasattr(app.state, "playback")

        # After the context exits, shutdown cancels the dispatcher task.
        assert app.state.gpio_dispatcher_task.done()


class TestImageHandler:
    """Image button → print content/last-cover (-k image)."""

    @pytest.fixture
    def last_cover(self, tmp_path, monkeypatch):
        from app.services import printer_handler

        path = tmp_path / "last-cover"
        monkeypatch.setattr(printer_handler, "LAST_COVER", path)
        return path

    @pytest.mark.asyncio
    async def test_image_prints_last_cover_and_rainbow(self, fake_clock, last_cover):
        last_cover.write_bytes(b"png")
        printer = MagicMock(print_sticker=AsyncMock())
        led = MagicMock()
        d = _dispatcher(printer=printer, led_animator=led, now=fake_clock)

        await d._handle_event("image")
        await _drain_tasks()

        printer.print_sticker.assert_awaited_once_with(last_cover)
        led.rainbow.assert_called_once()

    @pytest.mark.asyncio
    async def test_image_no_cover_yet_error_blink(self, fake_clock, last_cover):
        printer = MagicMock(print_sticker=AsyncMock())
        led = MagicMock()
        d = _dispatcher(printer=printer, led_animator=led, now=fake_clock)

        await d._handle_event("image")
        await _drain_tasks()

        printer.print_sticker.assert_not_called()
        led.set_mode.assert_called_with(Mode.ERROR)

    @pytest.mark.asyncio
    async def test_image_no_printer_error_blink(self, fake_clock, last_cover):
        last_cover.write_bytes(b"png")
        led = MagicMock()
        d = _dispatcher(printer=None, led_animator=led, now=fake_clock)

        await d._handle_event("image")  # must not raise

        led.set_mode.assert_called_with(Mode.ERROR)

    @pytest.mark.asyncio
    async def test_image_print_failure_error_blink(self, fake_clock, last_cover):
        last_cover.write_bytes(b"png")
        printer = MagicMock(print_sticker=AsyncMock(side_effect=OSError("off")))
        led = MagicMock()
        d = _dispatcher(printer=printer, led_animator=led, now=fake_clock)

        await d._handle_event("image")
        await _drain_tasks()

        led.set_mode.assert_called_with(Mode.ERROR)
        led.rainbow.assert_not_called()
        assert d._image_busy is False

    @pytest.mark.asyncio
    async def test_image_drop_on_busy(self, fake_clock, last_cover):
        last_cover.write_bytes(b"png")
        gate = asyncio.Event()

        async def slow_print(_path):
            await gate.wait()

        printer = MagicMock(print_sticker=AsyncMock(side_effect=slow_print))
        d = _dispatcher(printer=printer, now=fake_clock)

        await d._handle_event("image")
        await asyncio.sleep(0)
        fake_clock.now += 1.0
        await d._handle_event("image")  # in flight → dropped
        gate.set()
        await _drain_tasks()

        assert printer.print_sticker.await_count == 1


class TestSaveLastCover:
    def test_copies_and_overwrites(self, tmp_path, monkeypatch):
        from app.services import printer_handler

        dst = tmp_path / "last-cover"
        monkeypatch.setattr(printer_handler, "LAST_COVER", dst)
        a, b = tmp_path / "a.png", tmp_path / "b.jpg"
        a.write_bytes(b"A")
        b.write_bytes(b"B")

        printer_handler.save_last_cover(a)
        printer_handler.save_last_cover(b)

        assert dst.read_bytes() == b"B"
        assert not (tmp_path / "last-cover.tmp").exists()

    def test_missing_source_never_raises(self, tmp_path, monkeypatch):
        from app.services import printer_handler

        monkeypatch.setattr(printer_handler, "LAST_COVER", tmp_path / "last-cover")
        printer_handler.save_last_cover(tmp_path / "nope.png")


class TestPoweroffEndpoint:
    """BTN-06/D-04: POST /api/system/poweroff shares the poweroff helper."""

    def test_poweroff_endpoint_returns_ok(self):
        with pytest.MonkeyPatch.context() as mp:
            from app.services import system_control

            mp.setattr(system_control, "poweroff", AsyncMock())
            with TestClient(app) as client:
                response = client.post("/api/system/poweroff")
                assert response.status_code == 200
                assert response.json()["status"] == "ok"

    def test_poweroff_endpoint_calls_helper(self):
        from app.services import system_control

        poweroff = AsyncMock()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(system_control, "poweroff", poweroff)
            with TestClient(app) as client:
                client.post("/api/system/poweroff")

        poweroff.assert_awaited_once()
