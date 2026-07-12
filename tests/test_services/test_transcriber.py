"""Tests for the whisper.cpp transcription service (PLAN.md Task 4).

All subprocess work is mocked — the suite must never drive real
ffmpeg/whisper binaries (repo rule).
"""

from pathlib import Path

import pytest

from app.config import Settings
from app.services import transcriber


@pytest.fixture
def fake_tools(tmp_path, monkeypatch):
    """Fake whisper binary + model + ffmpeg so availability checks pass.

    Returns (settings, calls) where calls records every _run() command.
    Whisper invocations write a canned transcript to the -of prefix.
    """
    whisper_bin = tmp_path / "whisper-cli"
    whisper_bin.write_text("#!/bin/sh\n")
    whisper_bin.chmod(0o755)
    model = tmp_path / "ggml-small.bin"
    model.write_bytes(b"model")

    settings = Settings(
        transcription_enabled=True,
        whisper_bin=str(whisper_bin),
        whisper_model=str(model),
    )
    monkeypatch.setattr(transcriber, "get_settings", lambda: settings)
    monkeypatch.setattr(
        transcriber, "_which", lambda name: name if name != "missing" else None
    )

    calls: list[list[str]] = []

    async def fake_run(cmd):
        calls.append(cmd)
        if cmd[0] == str(whisper_bin):
            prefix = cmd[cmd.index("-of") + 1]
            Path(prefix + ".txt").write_text(" Había una vez un robot.\n")
        return 0

    monkeypatch.setattr(transcriber, "_run", fake_run)
    return settings, calls


class TestAvailabilityGuards:
    """transcribe() degrades to None instead of raising."""

    async def test_returns_none_when_disabled(self, fake_tools, monkeypatch):
        settings, calls = fake_tools
        monkeypatch.setattr(
            transcriber,
            "get_settings",
            lambda: settings.model_copy(update={"transcription_enabled": False}),
        )

        assert await transcriber.transcribe("audio.mp3") is None
        assert calls == []

    async def test_returns_none_when_whisper_binary_missing(
        self, fake_tools, monkeypatch
    ):
        settings, calls = fake_tools
        monkeypatch.setattr(
            transcriber,
            "get_settings",
            lambda: settings.model_copy(update={"whisper_bin": "missing"}),
        )

        assert await transcriber.transcribe("audio.mp3") is None
        assert calls == []

    async def test_returns_none_when_model_missing(self, fake_tools, monkeypatch):
        settings, calls = fake_tools
        monkeypatch.setattr(
            transcriber,
            "get_settings",
            lambda: settings.model_copy(
                update={"whisper_model": "/nonexistent/ggml.bin"}
            ),
        )

        assert await transcriber.transcribe("audio.mp3") is None
        assert calls == []

    async def test_returns_none_when_ffmpeg_missing(self, fake_tools, monkeypatch):
        _, calls = fake_tools
        monkeypatch.setattr(transcriber, "_which", lambda name: None)

        assert await transcriber.transcribe("audio.mp3") is None
        assert calls == []


class TestTranscribe:
    """Happy path and subprocess failures."""

    async def test_happy_path_returns_stripped_text(self, fake_tools):
        text = await transcriber.transcribe("audio.mp3")

        assert text == "Había una vez un robot."

    async def test_converts_to_16khz_mono_wav_before_whisper(self, fake_tools):
        await transcriber.transcribe("audio.mp3")

        settings, calls = fake_tools
        assert len(calls) == 2
        ffmpeg_cmd, whisper_cmd = calls
        assert ffmpeg_cmd[0] == "ffmpeg"
        assert "audio.mp3" in ffmpeg_cmd
        assert ["-ar", "16000"] == ffmpeg_cmd[ffmpeg_cmd.index("-ar") :][:2]
        assert ["-ac", "1"] == ffmpeg_cmd[ffmpeg_cmd.index("-ac") :][:2]
        # whisper consumes the wav ffmpeg produced
        wav = ffmpeg_cmd[-1]
        assert wav.endswith(".wav")
        assert wav in whisper_cmd

    async def test_whisper_runs_spanish_cpu_only_with_model(self, fake_tools):
        await transcriber.transcribe("audio.mp3")

        settings, calls = fake_tools
        whisper_cmd = calls[1]
        assert whisper_cmd[0] == settings.whisper_bin
        assert ["-m", settings.whisper_model] == (
            whisper_cmd[whisper_cmd.index("-m") :][:2]
        )
        assert ["-l", "es"] == whisper_cmd[whisper_cmd.index("-l") :][:2]
        assert "--no-gpu" in whisper_cmd

    async def test_returns_none_when_ffmpeg_fails(self, fake_tools, monkeypatch):
        async def failing_run(cmd):
            return 1

        monkeypatch.setattr(transcriber, "_run", failing_run)

        assert await transcriber.transcribe("audio.mp3") is None

    async def test_returns_none_when_whisper_fails(self, fake_tools, monkeypatch):
        settings, _ = fake_tools

        async def run(cmd):
            return 0 if cmd[0] == "ffmpeg" else 1

        monkeypatch.setattr(transcriber, "_run", run)

        assert await transcriber.transcribe("audio.mp3") is None

    async def test_returns_none_when_transcript_empty(self, fake_tools, monkeypatch):
        settings, _ = fake_tools

        async def run(cmd):
            if cmd[0] == settings.whisper_bin:
                Path(cmd[cmd.index("-of") + 1] + ".txt").write_text("  \n")
            return 0

        monkeypatch.setattr(transcriber, "_run", run)

        assert await transcriber.transcribe("audio.mp3") is None

    async def test_returns_none_when_run_times_out(self, fake_tools, monkeypatch):
        async def timing_out_run(cmd):
            raise TimeoutError

        monkeypatch.setattr(transcriber, "_run", timing_out_run)

        assert await transcriber.transcribe("audio.mp3") is None
