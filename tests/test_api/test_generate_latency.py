"""Backend pipeline latency regression test.

First-audio_ready arrival time under mock conditions — a regression guard
on backend pipeline overhead, NOT a Jetson production latency assertion.
Real Jetson end-to-end latency (POST to first audible PCM) is owned by
Phase 16 hardware verification.
"""

import json
import time
import wave
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.story_generator import StoryGenerator
from app.services.tts_pipeline import TTSPipeline


@pytest.fixture
def mock_story_generator():
    """Create a mock StoryGenerator and attach to app state."""
    sg = MagicMock(spec=StoryGenerator)
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


class TestGenerateLatency:
    def test_first_audio_ready_under_two_seconds(
        self, mock_story_generator, mock_tts_pipeline, tmp_path
    ):
        async def _fake_async_gen(events):
            for e in events:
                yield e

        mock_story_generator.generate_story.return_value = _fake_async_gen(
            [
                {"text": "Había una vez. ", "done": False},
                {"text": None, "done": True},
            ]
        )

        generated_dir = tmp_path / "content" / "generated"
        generated_dir.mkdir(parents=True)

        from app.routers import generate as gen_module

        original_dir = getattr(gen_module, "GENERATED_DIR", None)
        gen_module.GENERATED_DIR = generated_dir

        client = TestClient(app)

        try:
            start = time.monotonic()

            with client.stream(
                "POST",
                "/api/generate/story",
                json={
                    "parameters": [
                        {"category": "personaje", "value": "dragón"},
                    ]
                },
            ) as resp:
                assert resp.status_code == 200

                first_audio_at = None
                for line in resp.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    event = json.loads(line[6:])
                    if "audio_ready" in event:
                        first_audio_at = time.monotonic() - start
                        break

            assert first_audio_at is not None, "No audio_ready event received"
            assert first_audio_at < 2.0, (
                f"First audio_ready took {first_audio_at:.3f}s"
                " — backend overhead regression?"
            )
        finally:
            if original_dir is not None:
                gen_module.GENERATED_DIR = original_dir
            else:
                delattr(gen_module, "GENERATED_DIR")
