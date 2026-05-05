"""Tests for generate API endpoints."""

import json
import wave
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


async def _async_gen(events):
    """Convert a list of events into an async generator (for mocking)."""
    for e in events:
        yield e

from app.main import app
from app.services.story_generator import StoryGenerator
from app.services.tts_pipeline import TTSPipeline


@pytest.fixture
def mock_story_generator():
    """Create a mock StoryGenerator and attach to app state."""
    sg = MagicMock(spec=StoryGenerator)

    async def _fake_async_gen(events):
        for e in events:
            yield e

    # Default return value: a short two-event stream
    sg.generate_story.return_value = _fake_async_gen(
        [
            {"text": "Hola", "done": False},
            {"text": None, "done": True},
        ]
    )
    app.state.story_generator = sg
    yield sg
    delattr(app.state, "story_generator")


@pytest.fixture
def mock_tts_pipeline():
    """Create a mock TTSPipeline that writes dummy WAV files."""
    pipeline = MagicMock(spec=TTSPipeline)

    async def fake_synthesize(text: str, out_dir: Path, index: int) -> dict:
        audio_dir = out_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        wav_path = audio_dir / f"{index:03d}.wav"
        # Write minimal WAV
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(22050)
            wf.writeframes(b"\x00\x00" * 100)
        return {"index": index, "text": text, "audio": f"audio/{index:03d}.wav"}

    pipeline.synthesize_segment = fake_synthesize
    app.state.tts_pipeline = pipeline
    yield pipeline
    delattr(app.state, "tts_pipeline")


@pytest.fixture
def mock_tts_pipeline_failing():
    """Pipeline that always returns error metadata (no file written)."""
    pipeline = MagicMock(spec=TTSPipeline)

    async def failing_synthesize(text: str, out_dir: Path, index: int) -> dict:
        return {
            "index": index,
            "text": text,
            "error": "synth engine not loaded",
            "audio": None,
        }

    pipeline.synthesize_segment = failing_synthesize
    app.state.tts_pipeline = pipeline
    yield pipeline
    delattr(app.state, "tts_pipeline")


@pytest.fixture
def client(mock_story_generator, mock_tts_pipeline):
    """Test client with mock story generator and TTS pipeline."""
    return TestClient(app)


class TestGenerateStory:
    def test_generate_returns_sse(self, client, mock_story_generator):
        async def _fake_async_gen(events):
            for e in events:
                yield e

        mock_story_generator.generate_story.return_value = _fake_async_gen(
            [
                {"text": "Hola", "done": False},
                {"text": None, "done": True},
            ]
        )

        resp = client.post(
            "/api/generate/story",
            json={"parameters": [{"category": "personaje", "value": "dragón"}]},
        )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        lines = [l for l in resp.text.strip().split("\n") if l.startswith("data: ")]
        assert len(lines) >= 2
        first = json.loads(lines[0][6:])
        assert first["text"] == "Hola"
        assert first["done"] is False

    def test_generate_empty_params_returns_400(self, client):
        resp = client.post(
            "/api/generate/story", json={"parameters": []}
        )
        assert resp.status_code == 400

    def test_generate_error_streams_error(self, client, mock_story_generator):
        mock_story_generator.generate_story.return_value = _async_gen(
            [{"error": "llama-server no disponible", "done": True}]
        )

        resp = client.post(
            "/api/generate/story",
            json={"parameters": [{"category": "personaje", "value": "robot"}]},
        )

        assert resp.status_code == 200
        lines = [l for l in resp.text.strip().split("\n") if l.startswith("data: ")]
        first = json.loads(lines[0][6:])
        assert "error" in first
        assert first["done"] is True

    def test_generate_saves_story(self, client, mock_story_generator, tmp_path):
        mock_story_generator.generate_story.return_value = _async_gen(
            [
                {"text": "Había ", "done": False},
                {"text": "una vez.", "done": False},
                {"text": None, "done": True},
            ]
        )

        generated_dir = tmp_path / "content" / "generated"
        generated_dir.mkdir(parents=True)

        from app.routers import generate as gen_module

        original_dir = getattr(gen_module, "GENERATED_DIR", None)
        gen_module.GENERATED_DIR = generated_dir

        try:
            resp = client.post(
                "/api/generate/story",
                json={
                    "parameters": [
                        {"category": "personaje", "value": "gato"},
                        {"category": "lugar", "value": "jardín"},
                    ]
                },
            )
        finally:
            if original_dir is not None:
                gen_module.GENERATED_DIR = original_dir
            else:
                delattr(gen_module, "GENERATED_DIR")

        assert resp.status_code == 200

        saved = list(generated_dir.glob("*/story.json"))
        assert len(saved) == 1

        data = json.loads(saved[0].read_text())
        assert data["text"] == "Había una vez."
        assert len(data["parameters"]) == 2
        assert "created_at" in data


class TestGenerateStoryWithAudio:
    """Tests for interleaved audio_ready events (AC-3, AC-4)."""

    def _make_client_with_dir(
        self, mock_story_generator, mock_tts_pipeline, tmp_path
    ):
        generated_dir = tmp_path / "content" / "generated"
        generated_dir.mkdir(parents=True)

        from app.routers import generate as gen_module

        original_dir = getattr(gen_module, "GENERATED_DIR", None)
        gen_module.GENERATED_DIR = generated_dir

        client = TestClient(app)

        class Ctx:
            pass

        ctx = Ctx()
        ctx.client = client
        ctx.dir = generated_dir
        ctx._original_dir = original_dir
        return ctx

    def _restore_dir(self, ctx):
        from app.routers import generate as gen_module

        if ctx._original_dir is not None:
            gen_module.GENERATED_DIR = ctx._original_dir
        else:
            delattr(gen_module, "GENERATED_DIR")

    def test_two_sentences_emit_audio_ready_interleaved(
        self, mock_story_generator, mock_tts_pipeline, tmp_path
    ):
        """AC-3: SSE emits audio_ready events interleaved with text."""
        mock_story_generator.generate_story.return_value = _async_gen(
            [
                {"text": "Había una vez un dragón. ", "done": False},
                {"text": "Vivía en una montaña.", "done": False},
                {"text": None, "done": True},
            ]
        )

        ctx = self._make_client_with_dir(
            mock_story_generator, mock_tts_pipeline, tmp_path
        )
        try:
            resp = ctx.client.post(
                "/api/generate/story",
                json={"parameters": [{"category": "personaje", "value": "dragón"}]},
            )
        finally:
            self._restore_dir(ctx)

        assert resp.status_code == 200
        lines = [l for l in resp.text.strip().split("\n") if l.startswith("data: ")]
        events = [json.loads(l[6:]) for l in lines]

        # Find audio_ready events
        audio_events = [e for e in events if "audio_ready" in e]
        assert len(audio_events) == 2

        # Check ordering: done must be last
        done_indices = [i for i, e in enumerate(events) if e.get("done") is True]
        audio_indices = [i for i, e in enumerate(events) if "audio_ready" in e]
        assert all(ai < done_indices[0] for ai in audio_indices)

    def test_audio_ready_event_shape(
        self, mock_story_generator, mock_tts_pipeline, tmp_path
    ):
        """AC-3: audio_ready event has correct shape."""
        mock_story_generator.generate_story.return_value = _async_gen(
            [
                {"text": "Hola mundo. ", "done": False},
                {"text": None, "done": True},
            ]
        )

        ctx = self._make_client_with_dir(
            mock_story_generator, mock_tts_pipeline, tmp_path
        )
        try:
            resp = ctx.client.post(
                "/api/generate/story",
                json={"parameters": [{"category": "personaje", "value": "gato"}]},
            )
        finally:
            self._restore_dir(ctx)

        lines = [l for l in resp.text.strip().split("\n") if l.startswith("data: ")]
        events = [json.loads(l[6:]) for l in lines]
        audio_events = [e for e in events if "audio_ready" in e]
        assert len(audio_events) == 1

        ar = audio_events[0]["audio_ready"]
        assert ar["index"] == 0
        assert ar["text"] == "Hola mundo."
        assert "/static/generated/" in ar["url"]
        assert ar["url"].endswith("/audio/000.wav")
        assert audio_events[0]["done"] is False

    def test_story_json_has_segments(
        self, mock_story_generator, mock_tts_pipeline, tmp_path
    ):
        """AC-4: story.json contains segments manifest."""
        mock_story_generator.generate_story.return_value = _async_gen(
            [
                {"text": "Primero. ", "done": False},
                {"text": "Segundo!", "done": False},
                {"text": None, "done": True},
            ]
        )

        ctx = self._make_client_with_dir(
            mock_story_generator, mock_tts_pipeline, tmp_path
        )
        try:
            resp = ctx.client.post(
                "/api/generate/story",
                json={"parameters": [{"category": "personaje", "value": "perro"}]},
            )
        finally:
            self._restore_dir(ctx)

        saved = list(ctx.dir.glob("*/story.json"))
        assert len(saved) == 1
        data = json.loads(saved[0].read_text())
        assert "segments" in data
        assert len(data["segments"]) == 2
        assert data["segments"][0]["index"] == 0
        assert data["segments"][1]["index"] == 1

    def test_tail_sentence_flushed_and_synthesized(
        self, mock_story_generator, mock_tts_pipeline, tmp_path
    ):
        """Tail without terminal punctuation is flushed and synthesized."""
        mock_story_generator.generate_story.return_value = _async_gen(
            [
                {"text": "Un final abierto", "done": False},
                {"text": None, "done": True},
            ]
        )

        ctx = self._make_client_with_dir(
            mock_story_generator, mock_tts_pipeline, tmp_path
        )
        try:
            resp = ctx.client.post(
                "/api/generate/story",
                json={"parameters": [{"category": "personaje", "value": "oso"}]},
            )
        finally:
            self._restore_dir(ctx)

        lines = [l for l in resp.text.strip().split("\n") if l.startswith("data: ")]
        events = [json.loads(l[6:]) for l in lines]
        audio_events = [e for e in events if "audio_ready" in e]
        assert len(audio_events) == 1

        saved = list(ctx.dir.glob("*/story.json"))
        data = json.loads(saved[0].read_text())
        assert len(data["segments"]) == 1

    def test_synth_failure_emits_error_in_audio_ready(
        self, mock_story_generator, mock_tts_pipeline_failing, tmp_path
    ):
        """Synth failure emits audio_ready with error field, doesn't abort."""
        mock_story_generator.generate_story.return_value = _async_gen(
            [
                {"text": "Falla aquí. ", "done": False},
                {"text": None, "done": True},
            ]
        )

        ctx = self._make_client_with_dir(
            mock_story_generator, mock_tts_pipeline_failing, tmp_path
        )
        try:
            resp = ctx.client.post(
                "/api/generate/story",
                json={"parameters": [{"category": "personaje", "value": "pez"}]},
            )
        finally:
            self._restore_dir(ctx)

        lines = [l for l in resp.text.strip().split("\n") if l.startswith("data: ")]
        events = [json.loads(l[6:]) for l in lines]
        audio_events = [e for e in events if "audio_ready" in e]
        assert len(audio_events) == 1
        assert "error" in audio_events[0]["audio_ready"]
        # Stream should still complete normally
        done_events = [e for e in events if e.get("done") is True]
        assert len(done_events) == 1

    def test_existing_text_events_unchanged(
        self, mock_story_generator, mock_tts_pipeline, tmp_path
    ):
        """AC-5: existing text events per token are unchanged."""
        mock_story_generator.generate_story.return_value = _async_gen(
            [
                {"text": "Hola. ", "done": False},
                {"text": None, "done": True},
            ]
        )

        ctx = self._make_client_with_dir(
            mock_story_generator, mock_tts_pipeline, tmp_path
        )
        try:
            resp = ctx.client.post(
                "/api/generate/story",
                json={"parameters": [{"category": "personaje", "value": "gato"}]},
            )
        finally:
            self._restore_dir(ctx)

        lines = [l for l in resp.text.strip().split("\n") if l.startswith("data: ")]
        events = [json.loads(l[6:]) for l in lines]
        text_events = [e for e in events if e.get("text") is not None]
        assert len(text_events) == 1
        assert text_events[0]["text"] == "Hola. "
