"""An interrupted generated story still gets its cover, saved as last-cover.

The kiosk aborts the SSE request when the child presses the interrupt button.
The cover prompt depends only on the cards (params), so the cover can still be
drawn in the background and the image button prints it without the child
listening to the whole story.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.routers import generate
from app.routers.generate import StoryGenerateRequest, generate_story
from app.services import printer_handler


def _request(story_generator, orchestrator, story_manager):
    state = SimpleNamespace(
        ai_enabled=True,
        story_generator=story_generator,
        tts_pipeline=None,
        story_manager=story_manager,
        swap_orchestrator=orchestrator,
        led_animator=None,
    )
    return SimpleNamespace(app=SimpleNamespace(state=state))


def _endless_story():
    async def gen(_params):
        while True:
            yield {"text": "Había una vez. ", "done": False}
            await asyncio.sleep(0)

    sg = MagicMock()
    sg.generate_story = gen
    return sg


def _finite_story():
    async def gen(_params):
        yield {"text": "Un cuento. ", "done": False}
        yield {"text": None, "done": True}

    sg = MagicMock()
    sg.generate_story = gen
    return sg


@pytest.fixture
def cover_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        generate, "build_cover_prompt", AsyncMock(return_value=("pos", "neg"))
    )
    out = tmp_path / "cover-print.png"
    out.write_bytes(b"NEWCOVER")
    return out


async def _settle_covers():
    for _ in range(20):
        if not generate._cover_tasks:
            return
        await asyncio.gather(*list(generate._cover_tasks), return_exceptions=True)


BODY = StoryGenerateRequest(parameters=[{"category": "personaje", "value": "robot"}])


@pytest.mark.asyncio
async def test_interrupt_mid_story_still_generates_cover(cover_file):
    orch = AsyncMock()
    orch.generate_cover_for_story.return_value = (cover_file, cover_file, 1.0)
    sm = MagicMock()
    resp = await generate_story(BODY, _request(_endless_story(), orch, sm))

    it = resp.body_iterator
    await it.__anext__()  # first text chunk reached the kiosk
    await it.aclose()  # kiosk aborted the request (interrupt button)
    await _settle_covers()

    orch.generate_cover_for_story.assert_awaited_once()
    assert printer_handler.LAST_COVER.read_bytes() == b"NEWCOVER"
    sm.attach_cover.assert_not_called()  # the story itself was never saved


@pytest.mark.asyncio
async def test_disconnect_during_cover_keeps_cover_running(cover_file):
    release = asyncio.Event()
    started = asyncio.Event()

    async def slow_cover(*_a):
        started.set()
        await release.wait()
        return (cover_file, cover_file, 1.0)

    orch = AsyncMock()
    orch.generate_cover_for_story.side_effect = slow_cover
    sm = MagicMock()
    resp = await generate_story(BODY, _request(_finite_story(), orch, sm))

    async def consume():
        async for _ in resp.body_iterator:
            pass

    consumer = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), 5)
    consumer.cancel()  # Starlette cancels the response task on disconnect
    await asyncio.gather(consumer, return_exceptions=True)
    release.set()
    await _settle_covers()

    orch.generate_cover_for_story.assert_awaited_once()  # not restarted
    assert printer_handler.LAST_COVER.read_bytes() == b"NEWCOVER"
    sm.attach_cover.assert_called_once()  # story was saved before the cover


@pytest.mark.asyncio
async def test_completed_story_generates_cover_once(cover_file):
    orch = AsyncMock()
    orch.generate_cover_for_story.return_value = (cover_file, cover_file, 1.0)
    sm = MagicMock()
    resp = await generate_story(BODY, _request(_finite_story(), orch, sm))

    chunks = [c async for c in resp.body_iterator]
    await _settle_covers()

    assert any("cover_ready" in c for c in chunks)
    orch.generate_cover_for_story.assert_awaited_once()
    assert printer_handler.LAST_COVER.read_bytes() == b"NEWCOVER"
