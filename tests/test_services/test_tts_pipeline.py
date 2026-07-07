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


class RecordingSynthesizer(FakeSynthesizer):
    """Fake synth that records the speaker_id of each call."""

    def __init__(self):
        super().__init__()
        self.speaker_calls = []

    def synthesize(self, text: str, speaker_id=None) -> bytes:
        self.speaker_calls.append(speaker_id)
        return self._output


class TestSpeakerForwarding:
    """Pipeline forwards the per-story speaker to the synthesizer."""

    @pytest.mark.asyncio
    async def test_forwards_speaker_id(self, tmp_path):
        synth = RecordingSynthesizer()
        p = TTSPipeline(synth)
        meta = await p.synthesize_segment("Hola.", tmp_path, index=0, speaker_id=1)
        assert meta["audio"]
        assert synth.speaker_calls == [1]

    @pytest.mark.asyncio
    async def test_legacy_synth_without_speaker_kw_still_works(self, tmp_path):
        # A synthesizer exposing only synthesize(text) must keep working
        # when no speaker is requested.
        p = TTSPipeline(FakeSynthesizer())
        meta = await p.synthesize_segment("Hola.", tmp_path, index=0)
        assert meta["audio"]

    def test_pick_speaker_delegates_to_synthesizer(self):
        class PickingSynth(FakeSynthesizer):
            def pick_speaker(self):
                return 1

        assert TTSPipeline(PickingSynth()).pick_speaker() == 1

    def test_pick_speaker_none_when_synth_lacks_support(self):
        assert TTSPipeline(FakeSynthesizer()).pick_speaker() is None
