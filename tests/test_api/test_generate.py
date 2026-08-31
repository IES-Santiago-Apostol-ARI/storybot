"""Tests for generate API endpoints."""

import json
import wave
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import State

from app.main import app
from app.services.story_generator import StoryGenerator
from app.services.tts_pipeline import TTSPipeline


async def _async_gen(events):
    """Convert a list of events into an async generator (for mocking)."""
    for e in events:
        yield e


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
    app.state.ai_enabled = True
    yield sg
    delattr(app.state, "story_generator")
    delattr(app.state, "ai_enabled")


@pytest.fixture
def mock_tts_pipeline():
    """Create a mock TTSPipeline that writes dummy WAV files."""
    pipeline = MagicMock(spec=TTSPipeline)

    async def fake_synthesize(
        text: str, out_dir: Path, index: int, speaker_id=None
    ) -> dict:
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

    async def failing_synthesize(
        text: str, out_dir: Path, index: int, speaker_id=None
    ) -> dict:
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


class TestGenerateStoryParamValidation:
    """IMPROVE.md Task 6: parameter validation via Pydantic."""

    def test_empty_dict_in_params_returns_422(self, client):
        """{'parameters': [{}]} must be rejected with 422 before streaming."""
        resp = client.post("/api/generate/story", json={"parameters": [{}]})
        assert resp.status_code == 422

    def test_missing_category_returns_422(self, client):
        """Parameter without 'category' must be rejected with 422."""
        resp = client.post(
            "/api/generate/story",
            json={"parameters": [{"value": "dragón"}]},
        )
        assert resp.status_code == 422

    def test_missing_value_returns_422(self, client):
        """Parameter without 'value' must be rejected with 422."""
        resp = client.post(
            "/api/generate/story",
            json={"parameters": [{"category": "personaje"}]},
        )
        assert resp.status_code == 422

    def test_empty_string_category_returns_422(self, client):
        """Parameter with empty category must be rejected with 422."""
        resp = client.post(
            "/api/generate/story",
            json={"parameters": [{"category": "", "value": "dragón"}]},
        )
        assert resp.status_code == 422

    def test_empty_string_value_returns_422(self, client):
        """Parameter with empty value must be rejected with 422."""
        resp = client.post(
            "/api/generate/story",
            json={"parameters": [{"category": "personaje", "value": ""}]},
        )
        assert resp.status_code == 422

    def test_empty_list_still_returns_400(self, client):
        """{'parameters': []} must return the existing 400, not 422."""
        resp = client.post("/api/generate/story", json={"parameters": []})
        assert resp.status_code == 400

    def test_extra_keys_survive_to_story_json(
        self, client, mock_story_generator, tmp_path
    ):
        """Extra keys (emoji, label, etc.) survive to story.json."""
        mock_story_generator.generate_story.return_value = _async_gen(
            [{"text": "Hola.", "done": False}, {"text": None, "done": True}]
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
                        {
                            "category": "personaje",
                            "value": "dragón",
                            "emoji": "🐉",
                            "label": "Personaje",
                        }
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
        assert len(data["parameters"]) == 1
        param = data["parameters"][0]
        assert param["category"] == "personaje"
        assert param["value"] == "dragón"
        assert param["emoji"] == "🐉"
        assert param["label"] == "Personaje"

    def test_two_params_produce_same_prompt_as_before(
        self, client, mock_story_generator
    ):
        """Two valid parameters must produce the same prompt shape as before."""
        mock_story_generator.generate_story.return_value = _async_gen(
            [{"text": "Hola.", "done": False}, {"text": None, "done": True}]
        )

        resp = client.post(
            "/api/generate/story",
            json={
                "parameters": [
                    {"category": "personaje", "value": "gato"},
                    {"category": "lugar", "value": "jardín"},
                ]
            },
        )
        assert resp.status_code == 200

        # Verify the generator was called with dict params in order.
        call_args = mock_story_generator.generate_story.call_args
        params = call_args[0][0]
        assert isinstance(params, list)
        assert len(params) == 2
        assert params[0]["category"] == "personaje"
        assert params[0]["value"] == "gato"
        assert params[1]["category"] == "lugar"
        assert params[1]["value"] == "jardín"

        # Verify build_cover_prompt receives equivalent params. The pose and
        # framing are drawn at random per call, so both builds share one rng.
        from random import Random

        from app.services.cover_prompt_builder import build

        positive_after, _ = build(params, rng=Random(0))

        expected_params = [
            {"category": "personaje", "value": "gato"},
            {"category": "lugar", "value": "jardín"},
        ]
        positive_before, _ = build(expected_params, rng=Random(0))
        assert positive_after == positive_before


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

        lines = [
            line for line in resp.text.strip().split("\n") if line.startswith("data: ")
        ]
        assert len(lines) >= 2
        first = json.loads(lines[0][6:])
        assert first["text"] == "Hola"
        assert first["done"] is False

    def test_generate_empty_params_returns_400(self, client):
        resp = client.post("/api/generate/story", json={"parameters": []})
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
        lines = [
            line for line in resp.text.strip().split("\n") if line.startswith("data: ")
        ]
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

    def _make_client_with_dir(self, mock_story_generator, mock_tts_pipeline, tmp_path):
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
        lines = [
            line for line in resp.text.strip().split("\n") if line.startswith("data: ")
        ]
        events = [json.loads(line[6:]) for line in lines]

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

        lines = [
            line for line in resp.text.strip().split("\n") if line.startswith("data: ")
        ]
        events = [json.loads(line[6:]) for line in lines]
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
            ctx.client.post(
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

        lines = [
            line for line in resp.text.strip().split("\n") if line.startswith("data: ")
        ]
        events = [json.loads(line[6:]) for line in lines]
        audio_events = [e for e in events if "audio_ready" in e]
        assert len(audio_events) == 1

        saved = list(ctx.dir.glob("*/story.json"))
        data = json.loads(saved[0].read_text())
        assert len(data["segments"]) == 1

    def test_audio_complete_emitted_after_all_audio(
        self, mock_story_generator, mock_tts_pipeline, tmp_path
    ):
        """IMPROVEMENTS.md 1.1: one {"audio_complete": true} event follows the
        LAST audio_ready — including the flushed tail, which is emitted AFTER
        the {"text": None, "done": true} sentinel — so the kiosk can mark its
        playback queue complete while keeping the stream open for
        cover_ready/cover_failed."""
        mock_story_generator.generate_story.return_value = _async_gen(
            [
                {"text": "Primera frase. ", "done": False},
                {"text": "Cola sin punto final", "done": False},
                {"text": None, "done": True},
            ]
        )

        ctx = self._make_client_with_dir(
            mock_story_generator, mock_tts_pipeline, tmp_path
        )
        try:
            resp = ctx.client.post(
                "/api/generate/story",
                json={"parameters": [{"category": "personaje", "value": "lobo"}]},
            )
        finally:
            self._restore_dir(ctx)

        lines = [
            line for line in resp.text.strip().split("\n") if line.startswith("data: ")
        ]
        events = [json.loads(line[6:]) for line in lines]

        complete_indices = [
            i for i, e in enumerate(events) if e.get("audio_complete") is True
        ]
        assert (
            len(complete_indices) == 1
        ), f"expected exactly one audio_complete event; got {events}"

        audio_indices = [i for i, e in enumerate(events) if "audio_ready" in e]
        assert len(audio_indices) == 2  # terminated sentence + flushed tail
        assert all(
            ai < complete_indices[0] for ai in audio_indices
        ), "audio_complete must come after every audio_ready (incl. flushed tail)"

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

        lines = [
            line for line in resp.text.strip().split("\n") if line.startswith("data: ")
        ]
        events = [json.loads(line[6:]) for line in lines]
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

        lines = [
            line for line in resp.text.strip().split("\n") if line.startswith("data: ")
        ]
        events = [json.loads(line[6:]) for line in lines]
        text_events = [e for e in events if e.get("text") is not None]
        assert len(text_events) == 1
        assert text_events[0]["text"] == "Hola. "


class TestGenerateTruncatedStory:
    """IMPROVEMENTS.md 3.2: finish_reason == "length" (sentinel truncated=True)
    must NOT narrate the mid-word buffer tail as a sentence."""

    def _run(self, mock_story_generator, mock_tts_pipeline, tmp_path, events):
        mock_story_generator.generate_story.return_value = _async_gen(events)
        helper = TestGenerateStoryWithAudio()
        ctx = helper._make_client_with_dir(
            mock_story_generator, mock_tts_pipeline, tmp_path
        )
        try:
            resp = ctx.client.post(
                "/api/generate/story",
                json={"parameters": [{"category": "personaje", "value": "oso"}]},
            )
        finally:
            helper._restore_dir(ctx)
        lines = [
            line for line in resp.text.strip().split("\n") if line.startswith("data: ")
        ]
        return ctx, [json.loads(line[6:]) for line in lines]

    def test_truncated_tail_not_synthesized(
        self, mock_story_generator, mock_tts_pipeline, tmp_path
    ):
        """The fragment after the last complete sentence is dropped: no
        audio_ready for it, and the saved text ends at the sentence."""
        ctx, events = self._run(
            mock_story_generator,
            mock_tts_pipeline,
            tmp_path,
            [
                {"text": "Primera frase completa. ", "done": False},
                {"text": "Fragmento cortad", "done": False},
                {"text": None, "done": True, "truncated": True},
            ],
        )

        audio_events = [e for e in events if "audio_ready" in e]
        assert len(audio_events) == 1
        assert audio_events[0]["audio_ready"]["text"] == "Primera frase completa."

        # audio_complete still closes the audio phase for the kiosk.
        assert any(e.get("audio_complete") is True for e in events)

        saved = list(ctx.dir.glob("*/story.json"))
        assert len(saved) == 1
        data = json.loads(saved[0].read_text())
        assert data["text"] == "Primera frase completa."
        assert len(data["segments"]) == 1

    def test_truncated_stream_with_no_complete_sentence_saves_nothing(
        self, mock_story_generator, mock_tts_pipeline, tmp_path
    ):
        """All-fragment output (truncated before any terminator) narrates and
        saves nothing rather than a mid-word story."""
        ctx, events = self._run(
            mock_story_generator,
            mock_tts_pipeline,
            tmp_path,
            [
                {"text": "Fragmento cortad", "done": False},
                {"text": None, "done": True, "truncated": True},
            ],
        )

        assert not [e for e in events if "audio_ready" in e]
        assert list(ctx.dir.glob("*/story.json")) == []

    def test_untruncated_flush_behavior_unchanged(
        self, mock_story_generator, mock_tts_pipeline, tmp_path
    ):
        """Without truncated=True the tail is still flushed and narrated
        (pins that 3.2 only fires on finish_reason == "length")."""
        ctx, events = self._run(
            mock_story_generator,
            mock_tts_pipeline,
            tmp_path,
            [
                {"text": "Un final abierto", "done": False},
                {"text": None, "done": True},
            ],
        )

        audio_events = [e for e in events if "audio_ready" in e]
        assert len(audio_events) == 1
        assert audio_events[0]["audio_ready"]["text"] == "Un final abierto"


class TestPhase13Deployment:
    """Tests verifying deployment artifacts from Phase 13-02 (AC-3, AC-4)."""

    def test_llama_server_service_has_frozen_config(self):
        """AC-3: systemd unit contains the frozen launch config flags."""
        service_path = Path("deploy/llama-server.service")
        assert service_path.exists(), "llama-server.service must exist"
        content = service_path.read_text()

        # Frozen config from 13-01 report.md, retuned by IMPROVEMENTS.md 3.1
        # (2026-07-12): -c 2048 (prompt ~200 tok + output <=600) frees 192 MiB
        # of KV and lets all 33 layers offload to the GPU.
        assert "-c 2048" in content, "Must contain context size -c 2048"
        assert "--n-gpu-layers 99" in content, "Must offload all layers to GPU"
        assert "--no-mmap" in content, "Must disable mmap for safety"
        assert "--mlock" in content, "Must enable memory locking"
        assert "--reasoning off" in content, "Must disable reasoning output"

    def test_llama_server_service_restarts_on_failure(self):
        """AC-3: systemd unit has Restart=on-failure."""
        service_path = Path("deploy/llama-server.service")
        content = service_path.read_text()
        assert "Restart=on-failure" in content

    def test_storybot_depends_on_llama_server(self):
        """AC-3: storybot.service has After and Wants for llama-server."""
        svc_path = Path("deploy/storybot.service")
        content = svc_path.read_text()
        assert "llama-server.service" in content, "storybot must depend on llama-server"

    def test_no_ollama_in_pyproject(self):
        """AC-4: ollama dependency fully removed from pyproject.toml."""
        toml_path = Path("pyproject.toml")
        content = toml_path.read_text()
        assert (
            "ollama" not in content.lower()
        ), "ollama must be removed from dependencies"

    def test_no_ollama_imports_in_app(self):
        """AC-4: no app/ code imports ollama."""
        import subprocess

        result = subprocess.run(
            ["grep", "-r", "ollama", "app/", "--include=*.py"],
            capture_output=True,
            text=True,
            cwd=str(Path(".").resolve()),
        )
        assert result.returncode != 0, f"Found ollama imports in app/: {result.stdout}"

    def test_story_generator_default_params_match_report(self):
        """Verify StoryGenerator defaults match the recommended gen params from report.md."""
        from app.services.story_generator import StoryGenerator

        sg = StoryGenerator()
        assert sg.temperature == 0.8, "Default temp must be 0.8"
        assert sg.top_p == 0.95, "Default top_p must be 0.95"
        assert sg.max_tokens == 600, "Default max_tokens must be 600"

    def test_story_generator_model_name(self):
        """Verify model name matches the chosen Qwen 3.5 4B."""
        from app.services.story_generator import StoryGenerator

        sg = StoryGenerator()
        assert sg.model == "qwen35-4b-local", "Model must be qwen35-4b-local"

    def test_systemd_service_has_cuda_env(self):
        """AC-3: systemd unit sets CUDA environment variables."""
        service_path = Path("deploy/llama-server.service")
        content = service_path.read_text()
        assert "LD_LIBRARY_PATH" in content, "Must set LD_LIBRARY_PATH for CUDA"


# ---------------------------------------------------------------------------
# Phase 18-02: 503 AI-availability guard tests (API-02)
# ---------------------------------------------------------------------------


def _reset_app_state(app):
    """Clear app.state so attributes from a prior TestClient session don't leak."""
    app.state = State()


@pytest.fixture
def lifespan_env_ai_off(tmp_path, monkeypatch):
    """Lifespan env with AI forced OFF (STORYBOT_AI=0), TESTING deleted."""
    generated = tmp_path / "generated"
    generated.mkdir()
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.setenv("STORYBOT_AI", "0")
    monkeypatch.setenv("STORYBOT_LIFESPAN_TEST", "1")
    from app.services.story_manager import StoryManager

    monkeypatch.setattr(StoryManager, "GENERATED_DIR", generated)
    return generated


class TestGenerateAiGuard:
    """API-02: POST /api/generate/story returns 503 when AI is disabled."""

    def test_returns_503_when_ai_disabled(self, lifespan_env_ai_off):
        from app.main import app

        _reset_app_state(app)
        with TestClient(app) as client:
            resp = client.post(
                "/api/generate/story",
                json={"parameters": [{"category": "personaje", "value": "dragón"}]},
            )
            assert (
                resp.status_code == 503
            ), "API-02: must return 503 when ai_enabled=False"
            assert resp.json() == {
                "error": "AI not available on this device"
            }, "API-02: literal body shape locked"

    def test_guard_fires_before_param_validation(self, lifespan_env_ai_off):
        """503 must come BEFORE the 400 empty-params check (CONTEXT.md)."""
        from app.main import app

        _reset_app_state(app)
        with TestClient(app) as client:
            resp = client.post("/api/generate/story", json={"parameters": []})
            assert (
                resp.status_code == 503
            ), "API-02: AI guard must fire before 400 empty-params check"

    def test_succeeds_when_ai_enabled(self, client, mock_story_generator):
        """Existing 200 SSE path still works when ai_enabled=True."""

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

    def test_400_still_works_when_ai_enabled(self, client):
        """Existing 400 empty-params path still works when ai_enabled=True."""
        resp = client.post("/api/generate/story", json={"parameters": []})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Phase 33-05 (LED-17 / LED-20 / LED-15): generate-route LED triggers
# (RED first; GREEN after wiring the engine calls into generate.py).
# The engine is the sole writer — the route must drive it via
# app.state.led_animator; these tests spy on that animator to prove the
# three lifecycle hooks (start→thinking, audio_ready→progress, error→error)
# fire through the engine API with the defined neutral accent color
# (settings.led_accum_color, PLAN DECISION / D-21).
# ---------------------------------------------------------------------------


class TestGenerateLedTriggers:
    """LED-17 / LED-20 / LED-15: engine calls at generate lifecycle points."""

    def _attach_animator(self):
        """Attach a MagicMock animator to app.state and return it."""
        animator = MagicMock()
        app.state.led_animator = animator
        return animator

    def _detach_animator(self):
        """Remove the spy animator so other tests are unaffected."""
        if hasattr(app.state, "led_animator"):
            delattr(app.state, "led_animator")

    def test_generation_start_drives_thinking_mode(self, client, mock_story_generator):
        """LED-17: stream start -> animator.set_mode(Mode.THINKING)."""
        animator = self._attach_animator()
        try:
            from app.services.led_animator import Mode

            async def _gen(events):
                for e in events:
                    yield e

            mock_story_generator.generate_story.return_value = _gen(
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

            # LED-17: the engine was driven into THINKING at stream start.
            mode_calls = [c for c in animator.set_mode.call_args_list]
            assert any(
                call.args == (Mode.THINKING,) for call in mode_calls
            ), f"Expected set_mode(Mode.THINKING) at stream start; got {mode_calls}"
        finally:
            self._detach_animator()

    def test_audio_ready_drives_progress_mode_with_accum_color(
        self, client, mock_story_generator, mock_tts_pipeline, tmp_path
    ):
        """LED-20 / D-21: each audio_ready -> set_mode(Mode.PROGRESS, i, n,
        color=hex_to_rgb(settings.led_accum_color)) — defined neutral accent."""
        animator = self._attach_animator()
        from app.config import ConfigManager

        settings = ConfigManager().load()
        expected_color = _hex_to_rgb(settings.led_accum_color)

        from app.routers import generate as gen_module

        generated_dir = tmp_path / "content" / "generated"
        generated_dir.mkdir(parents=True)
        original_dir = getattr(gen_module, "GENERATED_DIR", None)
        gen_module.GENERATED_DIR = generated_dir

        try:
            from app.services.led_animator import Mode

            async def _gen(events):
                for e in events:
                    yield e

            mock_story_generator.generate_story.return_value = _gen(
                [
                    {"text": "Había una vez un dragón. ", "done": False},
                    {"text": "Vivía en una montaña.", "done": False},
                    {"text": None, "done": True},
                ]
            )

            resp = client.post(
                "/api/generate/story",
                json={"parameters": [{"category": "personaje", "value": "dragón"}]},
            )
            assert resp.status_code == 200

            # LED-20: at least one PROGRESS call fired with running-known-count N
            # (i == n each step, per PLAN DECISION) AND the defined neutral
            # accent color (settings.led_accum_color). This is the assertion that
            # makes LED-20's color verifiable (closes the prior "pin it in the
            # test" gap from 33-CONTEXT D-21).
            #
            # Note: Mode.PROGRESS and Mode.PARAM are IntEnum aliases (both value
            # 1 by D-13 design — they share the THINKING/param/progress priority
            # band). The engine dispatches on the integer value; the distinction
            # between a PARAM call (n_params=) and a PROGRESS call (i=/n=/color=)
            # is the kwarg signature. Filter on value==Mode.PROGRESS.value AND
            # the progress kwargs (i, n, color) so this precisely matches the
            # generate-route progress calls and not a param-accumulation call.
            progress_calls = [
                c
                for c in animator.set_mode.call_args_list
                if c.args
                and c.args[0] == Mode.PROGRESS.value
                and "i" in c.kwargs
                and "n" in c.kwargs
                and "color" in c.kwargs
            ]
            assert progress_calls, (
                f"Expected at least one set_mode(Mode.PROGRESS, i=, n=, "
                f"color=) call; got {animator.set_mode.call_args_list}"
            )

            # The first progress call must carry the resolved accum color and
            # running-known-count N (i == n).
            first = progress_calls[0]
            assert first.kwargs.get("color") == expected_color, (
                f"In-flight progress color must be the defined neutral accent "
                f"({settings.led_accum_color} -> {expected_color}); "
                f"got {first.kwargs.get('color')}"
            )
            assert first.kwargs.get("i") == first.kwargs.get("n"), (
                f"PLAN DECISION running-known-count N: i must equal n; "
                f"got i={first.kwargs.get('i')}, n={first.kwargs.get('n')}"
            )
        finally:
            if original_dir is not None:
                gen_module.GENERATED_DIR = original_dir
            else:
                delattr(gen_module, "GENERATED_DIR")
            self._detach_animator()

    def test_generation_error_drives_error_mode(self, client, mock_story_generator):
        """LED-15: a generation error event -> animator.set_mode(Mode.ERROR)."""
        animator = self._attach_animator()
        try:
            from app.services.led_animator import Mode

            async def _gen(events):
                for e in events:
                    yield e

            mock_story_generator.generate_story.return_value = _gen(
                [{"error": "llama-server no disponible", "done": True}]
            )

            resp = client.post(
                "/api/generate/story",
                json={"parameters": [{"category": "personaje", "value": "robot"}]},
            )
            assert resp.status_code == 200

            # LED-15: the engine was driven into ERROR mode (gentle amber, never
            # red / never strobe — D-09 / D-15). Driven through the engine, the
            # sole writer.
            mode_calls = animator.set_mode.call_args_list
            assert any(
                call.args == (Mode.ERROR,) for call in mode_calls
            ), f"Expected set_mode(Mode.ERROR) on generation error; got {mode_calls}"
        finally:
            self._detach_animator()

    def test_missing_animator_does_not_break_stream(self, client, mock_story_generator):
        """T-33-11: a missing engine degrades to no LED feedback, the stream
        still works (None-guard on every animator call)."""
        # Ensure no animator is set (mirrors TestClient-without-lifespan).
        self._detach_animator()
        assert not hasattr(app.state, "led_animator")

        async def _gen(events):
            for e in events:
                yield e

        mock_story_generator.generate_story.return_value = _gen(
            [
                {"text": "Hola", "done": False},
                {"text": None, "done": True},
            ]
        )

        resp = client.post(
            "/api/generate/story",
            json={"parameters": [{"category": "personaje", "value": "dragón"}]},
        )
        # Stream still works — no AttributeError from a missing engine.
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]


class TestGenerateStreamResilience:
    """IMPROVEMENTS.md 1.4 (route half): the SSE stream must never die
    silently nor strand the LED in THINKING/PROGRESS."""

    def test_midstream_exception_yields_error_event_and_error_mode(
        self, client, mock_story_generator
    ):
        """An unexpected exception inside the stream body must end the SSE
        with a terminal error event and drive the engine to ERROR — not
        propagate and abort the response with the LED stuck in THINKING."""
        from app.services.led_animator import Mode

        animator = MagicMock()
        app.state.led_animator = animator
        try:

            async def _boom():
                # No sentence terminator → no TTS side effects before the bang.
                yield {"text": "Hola", "done": False}
                raise RuntimeError("tts exploded")

            mock_story_generator.generate_story.return_value = _boom()

            resp = client.post(
                "/api/generate/story",
                json={"parameters": [{"category": "personaje", "value": "gato"}]},
            )
            assert resp.status_code == 200

            lines = [
                line
                for line in resp.text.strip().split("\n")
                if line.startswith("data: ")
            ]
            events = [json.loads(line[6:]) for line in lines]
            assert events, "stream produced no events"
            last = events[-1]
            assert last.get("error") == "RuntimeError"
            assert last.get("done") is True

            assert any(
                c.args == (Mode.ERROR,) for c in animator.set_mode.call_args_list
            ), f"expected set_mode(Mode.ERROR); got {animator.set_mode.call_args_list}"
        finally:
            delattr(app.state, "led_animator")

    @pytest.mark.asyncio
    async def test_client_disconnect_resets_led_to_idle(self):
        """GeneratorExit (kiosk tab closed mid-generation) must drive the
        engine to IDLE — nobody else will ever send the 'ended' state, so
        without this the LED stays in THINKING/PROGRESS forever."""
        from types import SimpleNamespace

        from app.routers.generate import StoryGenerateRequest, generate_story
        from app.services.led_animator import Mode

        animator = MagicMock()

        async def _slow_gen(parameters):
            yield {"text": "Hola ", "done": False}
            yield {"text": "mundo", "done": False}
            yield {"text": None, "done": True}

        state = SimpleNamespace(
            ai_enabled=True,
            story_generator=SimpleNamespace(generate_story=_slow_gen),
            led_animator=animator,
        )
        fastapi_request = SimpleNamespace(app=SimpleNamespace(state=state))

        resp = await generate_story(
            StoryGenerateRequest(
                parameters=[{"category": "personaje", "value": "gato"}]
            ),
            fastapi_request,
        )
        stream = resp.body_iterator
        first = await stream.__anext__()
        assert "Hola" in first

        await stream.aclose()  # client disconnect → GeneratorExit inside

        assert any(
            c.args == (Mode.IDLE,) for c in animator.set_mode.call_args_list
        ), f"expected set_mode(Mode.IDLE) on disconnect; got {animator.set_mode.call_args_list}"


def _hex_to_rgb(hex_color):
    """Local hex_to_rgb mirroring system.hex_to_rgb (avoids a cross-module import
    in the RED test; the assertion compares against the same resolved tuple)."""
    h = hex_color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


class TestGeneratedCap:
    """PLAN.md Task 3: at most 5 stories ever exist in content/generated/."""

    def _post(self, client, mock_story_generator, mock_tts_pipeline, tmp_path):
        """Helper: POST /api/generate/story, return saved story.json path."""
        from app.routers import generate as gen_module
        from app.services.story_manager import StoryManager

        generated_dir = tmp_path / "content" / "generated"
        generated_dir.mkdir(parents=True, exist_ok=True)

        # Reset the mock generator so each POST gets a fresh async gen.
        async def _make_gen():
            yield {"text": "Un cuento.", "done": False}
            yield {"text": None, "done": True}

        mock_story_generator.generate_story.return_value = _make_gen()

        # Point generate.py's GENERATED_DIR at tmp_path so _save_generated_story
        # and the TTS pipeline write into the test directory.
        original_dir = getattr(gen_module, "GENERATED_DIR", None)
        gen_module.GENERATED_DIR = generated_dir

        # Wire a real StoryManager onto app.state so the prune call in
        # generate.py actually runs (TestClient without 'with' skips lifespan).
        sm = StoryManager()
        sm.GENERATED_DIR = generated_dir
        app.state.story_manager = sm
        try:
            client.post(
                "/api/generate/story",
                json={"parameters": [{"category": "personaje", "value": "gato"}]},
            )
            saved = list(generated_dir.glob("*/story.json"))
            return saved
        finally:
            delattr(app.state, "story_manager")
            if original_dir is not None:
                gen_module.GENERATED_DIR = original_dir
            else:
                delattr(gen_module, "GENERATED_DIR")

    def test_sixth_generation_deletes_oldest(
        self, client, mock_story_generator, mock_tts_pipeline, tmp_path
    ):
        """After 6 generations, only the 5 newest story.json files remain."""
        for i in range(6):
            saved = self._post(
                client, mock_story_generator, mock_tts_pipeline, tmp_path
            )
            assert len(saved) == min(i + 1, 5)  # grows to the cap, never past it

        all_stories = list((tmp_path / "content" / "generated").glob("*/story.json"))
        assert len(all_stories) == 5, (
            f"Expected at most 5 generated stories, got {len(all_stories)}: "
            f"{sorted(s.parent.name for s in all_stories)}"
        )

    def test_single_generation_keeps_one(
        self, client, mock_story_generator, mock_tts_pipeline, tmp_path
    ):
        """First generation: exactly 1 story in generated dir."""
        self._post(client, mock_story_generator, mock_tts_pipeline, tmp_path)
        all_stories = list((tmp_path / "content" / "generated").glob("*/story.json"))
        assert len(all_stories) == 1


class TestGenerateTimingEvents:
    """IMPROVE.md Task 12: structured timing events on stderr for the generation
    pipeline. Events are stderr-only — the SSE body must be byte-identical to
    today. Each event is JSON with an 'event' key and numeric 'ms'."""

    def _run_with_timing(
        self, mock_story_generator, mock_tts_pipeline, tmp_path, events, monotonic_seq
    ):
        """Run a generation with mocked time.monotonic; return the SSE lines."""
        import time
        from unittest.mock import patch

        mock_story_generator.generate_story.return_value = _async_gen(events)

        generated_dir = tmp_path / "content" / "generated"
        generated_dir.mkdir(parents=True)

        from app.routers import generate as gen_module

        original_dir = getattr(gen_module, "GENERATED_DIR", None)
        gen_module.GENERATED_DIR = generated_dir

        seq_iter = iter(monotonic_seq)

        def fake_monotonic():
            return next(seq_iter)

        try:
            with patch.object(time, "monotonic", fake_monotonic):
                client = TestClient(app)
                resp = client.post(
                    "/api/generate/story",
                    json={"parameters": [{"category": "personaje", "value": "gato"}]},
                )
        finally:
            if original_dir is not None:
                gen_module.GENERATED_DIR = original_dir
            else:
                delattr(gen_module, "GENERATED_DIR")

        assert resp.status_code == 200
        return [
            line for line in resp.text.strip().split("\n") if line.startswith("data: ")
        ]

    def test_first_token_event_on_stderr(
        self, mock_story_generator, mock_tts_pipeline, tmp_path, capsys
    ):
        """gen_first_token emitted when first LLM text arrives in the streaming loop."""
        # Enough monotonic values: start + one per yield + buffer for TTS calls
        seq = list(range(100))

        self._run_with_timing(
            mock_story_generator,
            mock_tts_pipeline,
            tmp_path,
            [
                {"text": "Hola. ", "done": False},
                {"text": None, "done": True},
            ],
            seq,
        )

        stderr = capsys.readouterr().err
        events = [
            json.loads(line)
            for line in stderr.strip().split("\n")
            if line.strip().startswith("{")
        ]
        first_token = [e for e in events if e.get("event") == "gen_first_token"]
        assert len(first_token) == 1, f"expected one gen_first_token; got {events}"
        ft = first_token[0]
        assert "story_id" in ft
        assert isinstance(ft["ms"], (int, float))

    def test_segment_synth_events_on_stderr(
        self, mock_story_generator, mock_tts_pipeline, tmp_path, capsys
    ):
        """gen_segment_synth emitted at end of each _synth_and_events call."""
        seq = list(range(200))

        self._run_with_timing(
            mock_story_generator,
            mock_tts_pipeline,
            tmp_path,
            [
                {"text": "Primera. ", "done": False},
                {"text": "Segunda. ", "done": False},
                {"text": None, "done": True},
            ],
            seq,
        )

        stderr = capsys.readouterr().err
        events = [
            json.loads(line)
            for line in stderr.strip().split("\n")
            if line.strip().startswith("{")
        ]
        synth_events = [e for e in events if e.get("event") == "gen_segment_synth"]
        assert len(synth_events) == 2, f"expected two gen_segment_synth; got {events}"

        for i, se in enumerate(synth_events):
            assert se["index"] == i
            assert "story_id" in se
            assert "chars" in se
            assert isinstance(se["ms"], (int, float))

    def test_complete_event_on_stderr(
        self, mock_story_generator, mock_tts_pipeline, tmp_path, capsys
    ):
        """gen_complete emitted after audio_complete, with segment/char totals."""
        seq = list(range(200))

        self._run_with_timing(
            mock_story_generator,
            mock_tts_pipeline,
            tmp_path,
            [
                {"text": "Primera. ", "done": False},
                {"text": "Segunda.", "done": False},
                {"text": None, "done": True},
            ],
            seq,
        )

        stderr = capsys.readouterr().err
        events = [
            json.loads(line)
            for line in stderr.strip().split("\n")
            if line.strip().startswith("{")
        ]
        complete = [e for e in events if e.get("event") == "gen_complete"]
        assert len(complete) == 1, f"expected one gen_complete; got {events}"
        gc = complete[0]
        assert "story_id" in gc
        assert gc["segments"] == 2
        assert gc["chars"] == len("Primera. Segunda.")
        assert isinstance(gc["total_ms"], (int, float))
        assert gc["truncated"] is False

    def test_complete_event_truncated_true(
        self, mock_story_generator, mock_tts_pipeline, tmp_path, capsys
    ):
        """gen_complete.truncated mirrors the truncated sentinel."""
        seq = list(range(150))

        self._run_with_timing(
            mock_story_generator,
            mock_tts_pipeline,
            tmp_path,
            [
                {"text": "Primera. ", "done": False},
                {"text": "Cortad", "done": False},
                {"text": None, "done": True, "truncated": True},
            ],
            seq,
        )

        stderr = capsys.readouterr().err
        events = [
            json.loads(line)
            for line in stderr.strip().split("\n")
            if line.strip().startswith("{")
        ]
        complete = [e for e in events if e.get("event") == "gen_complete"]
        assert len(complete) == 1
        assert complete[0]["truncated"] is True

    def test_timing_events_not_in_sse(
        self, mock_story_generator, mock_tts_pipeline, tmp_path, capsys
    ):
        """Timing events are stderr-only — SSE body must be byte-identical to today."""
        seq = list(range(200))

        sse_lines = self._run_with_timing(
            mock_story_generator,
            mock_tts_pipeline,
            tmp_path,
            [
                {"text": "Hola. ", "done": False},
                {"text": None, "done": True},
            ],
            seq,
        )

        sse_text = "\n".join(sse_lines)
        for key in (
            "gen_first_token",
            "gen_segment_synth",
            "gen_complete",
            "gen_seconds",
        ):
            assert key not in sse_text, f"timing key '{key}' leaked into SSE body"

    def test_cover_generated_event_on_stderr(
        self, mock_story_generator, mock_tts_pipeline, tmp_path, capsys
    ):
        """cover_generated event emitted to stderr when cover finishes, carrying
        the same gen_seconds that goes to cover_ready."""
        from unittest.mock import MagicMock

        mock_story_generator.generate_story.return_value = _async_gen(
            [
                {"text": "Cuento. ", "done": False},
                {"text": None, "done": True},
            ]
        )

        generated_dir = tmp_path / "content" / "generated"
        generated_dir.mkdir(parents=True)

        from app.routers import generate as gen_module
        from app.services.story_manager import StoryManager
        from app.services.swap_orchestrator import SwapOrchestrator

        original_dir = getattr(gen_module, "GENERATED_DIR", None)
        gen_module.GENERATED_DIR = generated_dir

        orchestrator = MagicMock(spec=SwapOrchestrator)
        gen_seconds = 3.7
        preview = generated_dir / "test-id" / "cover-preview.png"
        print_path = generated_dir / "test-id" / "cover-print.png"
        preview.parent.mkdir(parents=True)
        preview.touch()
        print_path.touch()
        orchestrator.generate_cover_for_story.return_value = (
            preview,
            print_path,
            gen_seconds,
        )

        sm = StoryManager()
        sm.GENERATED_DIR = generated_dir

        app.state.swap_orchestrator = orchestrator
        app.state.story_manager = sm

        try:
            client = TestClient(app)
            resp = client.post(
                "/api/generate/story",
                json={"parameters": [{"category": "personaje", "value": "oso"}]},
            )
        finally:
            delattr(app.state, "swap_orchestrator")
            delattr(app.state, "story_manager")
            if original_dir is not None:
                gen_module.GENERATED_DIR = original_dir
            else:
                delattr(gen_module, "GENERATED_DIR")

        assert resp.status_code == 200

        stderr = capsys.readouterr().err
        events = [
            json.loads(line)
            for line in stderr.strip().split("\n")
            if line.strip().startswith("{")
        ]
        cover_events = [e for e in events if e.get("event") == "cover_generated"]
        assert len(cover_events) == 1, f"expected one cover_generated; got {events}"
        ce = cover_events[0]
        assert "story_id" in ce
        assert ce["gen_seconds"] == gen_seconds


class TestStorySpeakerConsistency:
    """One randomly picked voice per story, held across every segment."""

    def test_all_segments_use_the_story_speaker(self, mock_story_generator):
        pipeline = MagicMock(spec=TTSPipeline)
        pipeline.pick_speaker.return_value = 1
        captured: list = []

        async def fake_synthesize(
            text: str, out_dir: Path, index: int, speaker_id=None
        ) -> dict:
            captured.append(speaker_id)
            return {"index": index, "text": text, "audio": f"audio/{index:03d}.wav"}

        pipeline.synthesize_segment = fake_synthesize
        app.state.tts_pipeline = pipeline
        try:
            mock_story_generator.generate_story.return_value = _async_gen(
                [
                    {"text": "Primera frase. ", "done": False},
                    {"text": "Segunda frase. ", "done": False},
                    {"text": "Tercera frase. ", "done": False},
                    {"text": None, "done": True},
                ]
            )
            resp = TestClient(app).post(
                "/api/generate/story",
                json={"parameters": [{"category": "personaje", "value": "gato"}]},
            )
        finally:
            delattr(app.state, "tts_pipeline")

        assert resp.status_code == 200
        assert len(captured) >= 3
        assert set(captured) == {1}
        pipeline.pick_speaker.assert_called_once()
