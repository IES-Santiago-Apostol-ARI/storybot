"""Tests for cover generation SSE events — AC-4 + AC-7."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.story_generator import StoryGenerator
from app.services.story_manager import StoryManager
from app.services.swap_orchestrator import SwapOrchestrator
from app.services.tts_pipeline import TTSPipeline


@pytest.fixture
def mock_story_generator():
    sg = MagicMock(spec=StoryGenerator)
    sg.generate_story.return_value = (
        event
        for event in [
            {"text": "Un cuento. ", "done": False},
            {"text": None, "done": True},
        ]
    )
    # Make it async-compatible: wrap in an async generator
    async def _fake_async_gen(events):
        for e in events:
            yield e

    sg.generate_story.return_value = _fake_async_gen(
        [
            {"text": "Un cuento. ", "done": False},
            {"text": None, "done": True},
        ]
    )
    app.state.story_generator = sg
    app.state.ai_enabled = True
    yield sg
    delattr(app.state, "story_generator")
    delattr(app.state, "ai_enabled")


@pytest.fixture
def mock_story_manager():
    sm = MagicMock(spec=StoryManager)
    app.state.story_manager = sm
    yield sm
    delattr(app.state, "story_manager")


@pytest.fixture
def mock_tts():
    pipeline = MagicMock(spec=TTSPipeline)

    async def fake_synthesize(text, out_dir, index):
        return {"index": index, "text": text, "audio": None, "error": "no engine"}

    pipeline.synthesize_segment = fake_synthesize
    app.state.tts_pipeline = pipeline
    yield pipeline
    delattr(app.state, "tts_pipeline")


def _setup_dir(tmp_path):
    from app.routers import generate as gen_module

    generated_dir = tmp_path / "content" / "generated"
    generated_dir.mkdir(parents=True)
    original = getattr(gen_module, "GENERATED_DIR", None)
    gen_module.GENERATED_DIR = generated_dir
    return generated_dir, original


def _restore_dir(original):
    from app.routers import generate as gen_module

    if original is not None:
        gen_module.GENERATED_DIR = original
    else:
        delattr(gen_module, "GENERATED_DIR")


class TestCoverReadyEmitted:
    """Cover generation success → cover_ready SSE event."""

    def test_cover_ready_on_success(
        self, mock_story_generator, mock_story_manager, mock_tts, tmp_path
    ):
        orchestrator = AsyncMock(spec=SwapOrchestrator)
        orchestrator.generate_cover_for_story.return_value = (
            Path("/tmp/preview.png"),
            Path("/tmp/print.png"),
            9.5,
        )
        app.state.swap_orchestrator = orchestrator

        generated_dir, original = _setup_dir(tmp_path)
        try:
            client = TestClient(app)
            resp = client.post(
                "/api/generate/story",
                json={"parameters": [{"category": "personaje", "value": "robot"}]},
            )
        finally:
            _restore_dir(original)
            delattr(app.state, "swap_orchestrator")

        assert resp.status_code == 200

        # Parse SSE events
        text = resp.text
        assert "cover_ready" in text
        for line in text.split("\n"):
            if line.startswith("data: ") and "cover_ready" in line:
                data = json.loads(line[6:])
                assert "cover_ready" in data
                cover = data["cover_ready"]
                assert "/static/generated/" in cover["preview_url"]
                assert cover["gen_seconds"] == 9.5
                break

    def test_attach_cover_called_on_success(
        self, mock_story_generator, mock_story_manager, mock_tts, tmp_path
    ):
        orchestrator = AsyncMock(spec=SwapOrchestrator)
        orchestrator.generate_cover_for_story.return_value = (
            Path("/tmp/preview.png"),
            Path("/tmp/print.png"),
            5.0,
        )
        app.state.swap_orchestrator = orchestrator

        generated_dir, original = _setup_dir(tmp_path)
        try:
            client = TestClient(app)
            resp = client.post(
                "/api/generate/story",
                json={"parameters": [{"category": "personaje", "value": "gato"}]},
            )
        finally:
            _restore_dir(original)
            delattr(app.state, "swap_orchestrator")

        assert resp.status_code == 200
        mock_story_manager.attach_cover.assert_called_once()
        call_args = mock_story_manager.attach_cover.call_args
        assert "preview.png" in call_args[0][1]
        assert "print.png" in call_args[0][2]


class TestCoverFailedEmitted:
    """Cover generation failure → cover_failed SSE event."""

    def test_cover_failed_on_orchestrator_none(
        self, mock_story_generator, mock_story_manager, mock_tts, tmp_path
    ):
        orchestrator = AsyncMock(spec=SwapOrchestrator)
        orchestrator.generate_cover_for_story.return_value = (
            None,
            None,
            None,
        )
        app.state.swap_orchestrator = orchestrator

        generated_dir, original = _setup_dir(tmp_path)
        try:
            client = TestClient(app)
            resp = client.post(
                "/api/generate/story",
                json={"parameters": [{"category": "personaje", "value": "pez"}]},
            )
        finally:
            _restore_dir(original)
            delattr(app.state, "swap_orchestrator")

        assert resp.status_code == 200
        text = resp.text
        assert "cover_failed" in text

        # Story still saved (no cover key)
        saved = list(generated_dir.glob("*/story.json"))
        data = json.loads(saved[0].read_text())
        assert "cover" not in data

    def test_cover_failed_on_exception(
        self, mock_story_generator, mock_story_manager, mock_tts, tmp_path
    ):
        orchestrator = AsyncMock(spec=SwapOrchestrator)
        orchestrator.generate_cover_for_story.side_effect = RuntimeError("boom")
        app.state.swap_orchestrator = orchestrator

        generated_dir, original = _setup_dir(tmp_path)
        try:
            client = TestClient(app)
            resp = client.post(
                "/api/generate/story",
                json={"parameters": [{"category": "personaje", "value": "oso"}]},
            )
        finally:
            _restore_dir(original)
            delattr(app.state, "swap_orchestrator")

        assert resp.status_code == 200
        assert "cover_failed" in resp.text

    def test_no_cover_events_without_orchestrator(
        self, mock_story_generator, mock_story_manager, mock_tts, tmp_path
    ):
        # No orchestrator registered
        if hasattr(app.state, "swap_orchestrator"):
            delattr(app.state, "swap_orchestrator")

        generated_dir, original = _setup_dir(tmp_path)
        try:
            client = TestClient(app)
            resp = client.post(
                "/api/generate/story",
                json={"parameters": [{"category": "personaje", "value": "lobo"}]},
            )
        finally:
            _restore_dir(original)

        assert resp.status_code == 200
        assert "cover_ready" not in resp.text
        assert "cover_failed" not in resp.text


class TestAudioStillFlows:
    """Audio events are unaffected by cover generation."""

    def test_audio_ready_present_with_cover(
        self, mock_story_generator, mock_story_manager, tmp_path
    ):
        """Audio_ready events flow even when cover gen is active."""

        # Real-ish TTS that creates a file
        pipeline = MagicMock(spec=TTSPipeline)

        async def fake_synthesize(text, out_dir, index):
            audio_dir = Path(str(out_dir)) / "audio"
            audio_dir.mkdir(parents=True, exist_ok=True)
            wav = audio_dir / f"{index:03d}.wav"
            import wave

            with wave.open(str(wav), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(22050)
                wf.writeframes(b"\x00\x00" * 100)
            return {
                "index": index,
                "text": text,
                "audio": f"audio/{index:03d}.wav",
            }

        pipeline.synthesize_segment = fake_synthesize
        app.state.tts_pipeline = pipeline

        orchestrator = AsyncMock(spec=SwapOrchestrator)
        orchestrator.generate_cover_for_story.return_value = (
            Path("/tmp/p.png"),
            Path("/tmp/q.png"),
            1.0,
        )
        app.state.swap_orchestrator = orchestrator

        generated_dir, original = _setup_dir(tmp_path)
        try:
            client = TestClient(app)
            resp = client.post(
                "/api/generate/story",
                json={"parameters": [{"category": "personaje", "value": "zorro"}]},
            )
        finally:
            _restore_dir(original)
            delattr(app.state, "swap_orchestrator")

        lines = [
            ln for ln in resp.text.split("\n") if ln.startswith("data: ")
        ]
        events = [json.loads(ln[6:]) for ln in lines]

        audio_events = [e for e in events if "audio_ready" in e]
        assert len(audio_events) >= 1, "audio_ready events must still flow"

        # Cover event also present
        assert "cover_ready" in resp.text


class TestAttachCover:
    """Direct tests for StoryManager.attach_cover — AC-5."""

    def test_adds_cover_key_to_story_json(self, tmp_path):
        from app.services.story_manager import StoryManager

        gen_dir = tmp_path / "generated"
        gen_dir.mkdir(parents=True)
        story_dir = gen_dir / "test-story-id"
        story_dir.mkdir()
        story_file = story_dir / "story.json"
        story_file.write_text(
            json.dumps(
                {
                    "id": "test-story-id",
                    "text": "Hola",
                    "parameters": [],
                    "created_at": "2026-04-27T00:00:00Z",
                }
            )
        )

        sm = StoryManager()
        sm.GENERATED_DIR = gen_dir
        sm.attach_cover("test-story-id", "/tmp/preview.png", "/tmp/print.png")

        data = json.loads(story_file.read_text())
        assert "cover" in data
        assert data["cover"]["preview"] == "cover-preview.png"
        assert data["cover"]["print"] == "cover-print.png"
        assert "generated_at" in data["cover"]

    def test_overwrites_existing_cover(self, tmp_path):
        from app.services.story_manager import StoryManager

        gen_dir = tmp_path / "generated"
        gen_dir.mkdir(parents=True)
        story_dir = gen_dir / "story-2"
        story_dir.mkdir()
        story_file = story_dir / "story.json"
        story_file.write_text(
            json.dumps(
                {
                    "id": "story-2",
                    "text": "Test",
                    "parameters": [],
                    "created_at": "2026-04-27T00:00:00Z",
                    "cover": {
                        "preview": "old.png",
                        "print": "old.png",
                        "generated_at": "old-ts",
                    },
                }
            )
        )

        sm = StoryManager()
        sm.GENERATED_DIR = gen_dir
        sm.attach_cover("story-2", "/tmp/new.png", "/tmp/new.png")

        data = json.loads(story_file.read_text())
        assert data["cover"]["preview"] == "cover-preview.png"
        assert data["cover"]["generated_at"] != "old-ts"

    def test_silent_return_on_missing_story(self, tmp_path, capsys):
        from app.services.story_manager import StoryManager

        sm = StoryManager()
        sm.attach_cover("nonexistent", "/tmp/p.png", "/tmp/q.png")
        # Should not raise
        captured = capsys.readouterr()
        assert "cover_attach_orphan" in captured.err
