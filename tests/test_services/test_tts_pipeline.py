"""Tests for TTSPipeline — sentence to WAV segment persistence."""

import struct
import wave

import pytest

from app.services.tts_pipeline import TTSPipeline


def _make_fake_wav(duration_samples: int = 2205) -> bytes:
    """Minimal valid WAV: mono int16 at 22050Hz, silence."""
    raw = b"\x00\x00" * duration_samples
    buf = bytearray()
    n_channels = 1
    sample_width = 2
    framerate = 22050
    data_size = len(raw)
    buf.extend(b"RIFF")
    buf.extend(struct.pack("<I", 36 + data_size))
    buf.extend(b"WAVE")
    buf.extend(b"fmt ")
    buf.extend(struct.pack("<I", 16))
    buf.extend(struct.pack("<HHIIHH", 1, n_channels, framerate, framerate * n_channels * sample_width, n_channels * sample_width, sample_width * 8))
    buf.extend(b"data")
    buf.extend(struct.pack("<I", data_size))
    buf.extend(raw)
    return bytes(buf)


FAKE_WAV = _make_fake_wav()


class FakeSynthesizer:
    """Duck-typed synthesizer for testing."""

    def __init__(self, output: bytes = FAKE_WAV):
        self._output = output

    def synthesize(self, text: str) -> bytes:
        return self._output


class FailingSynthesizer:
    """Synthesizer that always raises."""

    def synthesize(self, text: str) -> bytes:
        raise RuntimeError("synth engine crashed")


@pytest.fixture
def pipeline():
    return TTSPipeline(FakeSynthesizer())


@pytest.fixture
def failing_pipeline():
    return TTSPipeline(FailingSynthesizer())


class TestTTSPipelineWrite:
    @pytest.mark.asyncio
    async def test_writes_wav_file(self, pipeline, tmp_path):
        out_dir = tmp_path / "story"
        meta = await pipeline.synthesize_segment("Hola.", out_dir, index=0)

        wav_path = out_dir / "audio" / "000.wav"
        assert wav_path.exists()
        # Verify it's a valid WAV
        with wave.open(str(wav_path), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 22050

    @pytest.mark.asyncio
    async def test_metadata_fields(self, pipeline, tmp_path):
        out_dir = tmp_path / "story"
        meta = await pipeline.synthesize_segment("Hola mundo.", out_dir, index=0)

        assert meta["index"] == 0
        assert meta["text"] == "Hola mundo."
        assert meta["audio"] == "audio/000.wav"

    @pytest.mark.asyncio
    async def test_index_padding(self, pipeline, tmp_path):
        out_dir = tmp_path / "story"
        for idx, expected_name in [
            (0, "000.wav"),
            (9, "009.wav"),
            (10, "010.wav"),
            (99, "099.wav"),
            (100, "100.wav"),
        ]:
            meta = await pipeline.synthesize_segment("test", out_dir, index=idx)
            assert meta["audio"] == f"audio/{expected_name}"


class TestTTSPipelineFailure:
    @pytest.mark.asyncio
    async def test_synth_failure_returns_error_no_raise(self, failing_pipeline, tmp_path):
        out_dir = tmp_path / "story"
        meta = await failing_pipeline.synthesize_segment("fail", out_dir, index=0)

        assert "error" in meta
        assert meta["audio"] is None
        assert meta["index"] == 0

    @pytest.mark.asyncio
    async def test_no_partial_file_on_failure(self, failing_pipeline, tmp_path):
        out_dir = tmp_path / "story"
        await failing_pipeline.synthesize_segment("fail", out_dir, index=0)

        wav_path = out_dir / "audio" / "000.wav"
        assert not wav_path.exists()


class TestTTSPipelineDirCreation:
    @pytest.mark.asyncio
    async def test_creates_out_dir(self, pipeline, tmp_path):
        out_dir = tmp_path / "nested" / "story"
        await pipeline.synthesize_segment("test", out_dir, index=0)
        assert (out_dir / "audio").is_dir()
