"""Tests for GpioDispatcher service and the poweroff endpoint.

Verifies the four button-name actions wired by Phase 36 against the deterministic
seams (no hardware):

- debounce (D-02/BTN-07): exactly one dispatch per press within gpio_debounce_ms
- power (BTN-01/D-03): delegates to system_control.poweroff()
- interrupt (BTN-02/D-05): audio stop + clear PlaybackState + {type:interrupt}
- animation (BTN-05/D-11): LedAnimator.rainbow() one-shot
- lifespan (D-01): dispatcher task created on startup, cancelled cleanly
- image (BTN-03/04/D-08/09/10): background cover gen, drop-on-busy, success ack,
  failure/None-orchestrator error blink, nothing-playing / no-params fallback
- POST /api/system/poweroff shares the poweroff helper (BTN-06/D-04)
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
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
            assert isinstance(app.state.kiosk_events, asyncio.Queue)
            assert app.state.kiosk_events is not app.state.gpio_events
            assert hasattr(app.state, "playback")

        # After the context exits, shutdown cancels the dispatcher task.
        assert app.state.gpio_dispatcher_task.done()


class TestImageHandler:
    """BTN-03/04: image button → background cover generation (-k image)."""

    @pytest.mark.asyncio
    async def test_image_success_enqueues_event_and_rainbow_ack(self, fake_clock):
        orch = MagicMock()
        orch.generate_cover_for_story = AsyncMock(
            return_value=(Path("/x/cover-preview.png"), Path("/x/cover-print.png"), 4.2)
        )
        led = MagicMock()
        kiosk: asyncio.Queue = asyncio.Queue()
        holder = _holder(
            {
                "story_id": "story-1",
                "params": [{"category": "personaje", "value": "gato"}],
                "title": "Cuento",
            }
        )
        d = _dispatcher(
            kiosk_events=kiosk,
            swap_orchestrator=orch,
            led_animator=led,
            playback_holder=holder,
            now=fake_clock,
        )

        await d._handle_event("image")
        await _drain_tasks()

        orch.generate_cover_for_story.assert_awaited_once()
        assert orch.generate_cover_for_story.call_args[0][0] == "story-1"
        assert kiosk.get_nowait() == {
            "type": "image",
            "url": "/static/generated/story-1/cover-preview.png",
        }
        led.rainbow.assert_called_once()

    @pytest.mark.asyncio
    async def test_image_drop_on_busy(self, fake_clock):
        release = asyncio.Event()
        calls: list[str] = []

        async def slow_gen(story_id, positive, negative, seed):
            calls.append(story_id)
            await release.wait()
            return (Path("/x/cover-preview.png"), Path("/x/cover-print.png"), 1.0)

        orch = MagicMock()
        orch.generate_cover_for_story = slow_gen
        holder = _holder({"story_id": "story-1", "params": [], "title": "T"})
        d = _dispatcher(swap_orchestrator=orch, playback_holder=holder, now=fake_clock)

        await d._handle_event("image")  # starts generation → busy
        await asyncio.sleep(0)
        fake_clock.now += 1.0  # bypass debounce so busy-guard is the cause
        await d._handle_event("image")  # in flight → DROPPED
        await asyncio.sleep(0)

        assert len(calls) == 1

        release.set()
        await _drain_tasks()

    @pytest.mark.asyncio
    async def test_image_failure_drives_error_blink(self, fake_clock):
        orch = MagicMock()
        orch.generate_cover_for_story = AsyncMock(return_value=(None, None, None))
        led = MagicMock()
        kiosk: asyncio.Queue = asyncio.Queue()
        holder = _holder({"story_id": "story-1", "params": [], "title": "T"})
        d = _dispatcher(
            kiosk_events=kiosk,
            swap_orchestrator=orch,
            led_animator=led,
            playback_holder=holder,
            now=fake_clock,
        )

        await d._handle_event("image")
        await _drain_tasks()

        led.set_mode.assert_called_with(Mode.ERROR)
        assert kiosk.empty()

    @pytest.mark.asyncio
    async def test_image_none_orchestrator_error_blink(self, fake_clock):
        led = MagicMock()
        kiosk: asyncio.Queue = asyncio.Queue()
        holder = _holder({"story_id": "story-1", "params": [], "title": "T"})
        d = _dispatcher(
            kiosk_events=kiosk,
            swap_orchestrator=None,
            led_animator=led,
            playback_holder=holder,
            now=fake_clock,
        )

        await d._handle_event("image")  # must not raise
        await _drain_tasks()

        led.set_mode.assert_called_with(Mode.ERROR)
        assert kiosk.empty()


class TestImageEdgeCases:
    """BTN-04/D-10 edge cases (-k image_edge)."""

    @pytest.mark.asyncio
    async def test_image_edge_nothing_playing(self, fake_clock):
        orch = MagicMock()
        orch.generate_cover_for_story = AsyncMock()
        led = MagicMock()
        kiosk: asyncio.Queue = asyncio.Queue()
        holder = _holder(None)  # nothing playing
        d = _dispatcher(
            kiosk_events=kiosk,
            swap_orchestrator=orch,
            led_animator=led,
            playback_holder=holder,
            now=fake_clock,
        )

        await d._handle_event("image")
        await _drain_tasks()

        orch.generate_cover_for_story.assert_not_called()
        led.set_mode.assert_called_with(Mode.ERROR)
        assert kiosk.empty()

    @pytest.mark.asyncio
    async def test_image_edge_no_params_title_fallback(self, fake_clock):
        from app.services import gpio_dispatcher

        captured: dict = {}

        def spy_build(params):
            captured["params"] = params
            return ("positive", "negative")

        orch = MagicMock()
        orch.generate_cover_for_story = AsyncMock(
            return_value=(Path("/x/cover-preview.png"), Path("/x/print.png"), 1.0)
        )
        holder = _holder(
            {"story_id": "story-1", "params": [], "title": "Cuento de Ana"}
        )
        d = _dispatcher(swap_orchestrator=orch, playback_holder=holder, now=fake_clock)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(gpio_dispatcher.cover_prompt_builder, "build", spy_build)
            await d._handle_event("image")
            await _drain_tasks()

        assert captured["params"] == [
            {"category": "personaje", "value": "Cuento de Ana"}
        ]
        orch.generate_cover_for_story.assert_awaited_once()


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
