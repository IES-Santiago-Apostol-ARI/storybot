"""Audio transcription via whisper.cpp (PLAN.md Task 4).

Converts an uploaded story audio file (mp3/wav) to 16 kHz mono WAV with
ffmpeg, then runs whisper-cli on it. Everything degrades to None: missing
binaries, a failed subprocess or an empty transcript never break the upload.

Runs CPU-only (--no-gpu): transcription is an occasional admin action and
must not fight llama-server/SD for the Jetson's unified 8 GB memory.
"""

import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

from app.config import get_settings

# Whisper language; all shipped voices/stories are Spanish (es_ES).
LANGUAGE = "es"
# Generous cap per subprocess; a hung ffmpeg/whisper must not pin the
# serialization lock forever.
SUBPROCESS_TIMEOUT_S = 600

# Transcriptions are serialized: concurrent admin uploads must not stack
# multiple whisper processes on the 8 GB Jetson.
_LOCK = asyncio.Lock()

# Seam for tests (and PATH resolution of a bare "whisper-cli").
_which = shutil.which


def _log(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}), file=sys.stderr)


async def _run(cmd: list[str]) -> int:
    """Run a command, discarding output. Returns the exit code."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=SUBPROCESS_TIMEOUT_S
        )
    except (TimeoutError, asyncio.TimeoutError):
        proc.kill()
        await proc.wait()
        raise TimeoutError(f"{cmd[0]} timed out after {SUBPROCESS_TIMEOUT_S}s")
    if proc.returncode != 0:
        _log(
            "transcribe_subprocess_failed",
            cmd=cmd[0],
            returncode=proc.returncode,
            stderr=stderr.decode(errors="replace")[-500:],
        )
    return proc.returncode


def _resolve_tools() -> tuple[str, str, str] | None:
    """Return (whisper_bin, whisper_model, ffmpeg) paths, or None if any is
    missing/disabled."""
    settings = get_settings()
    if not settings.transcription_enabled:
        return None
    whisper_bin = _which(settings.whisper_bin)
    ffmpeg = _which("ffmpeg")
    model_ok = Path(settings.whisper_model).exists()
    if not whisper_bin or not ffmpeg or not model_ok:
        _log(
            "transcribe_unavailable",
            whisper_bin=bool(whisper_bin),
            whisper_model=model_ok,
            ffmpeg=bool(ffmpeg),
        )
        return None
    return whisper_bin, settings.whisper_model, ffmpeg


async def transcribe(audio_path: Path | str) -> str | None:
    """Transcribe a story audio file to text. Returns None on any failure."""
    tools = _resolve_tools()
    if tools is None:
        return None
    whisper_bin, whisper_model, ffmpeg = tools

    async with _LOCK:
        with tempfile.TemporaryDirectory(prefix="storybot-stt-") as td:
            wav = Path(td) / "audio-16k.wav"
            out_prefix = Path(td) / "transcript"
            try:
                rc = await _run(
                    [
                        ffmpeg,
                        "-y",
                        "-i",
                        str(audio_path),
                        "-ar",
                        "16000",
                        "-ac",
                        "1",
                        str(wav),
                    ]
                )
                if rc != 0:
                    return None
                rc = await _run(
                    [
                        whisper_bin,
                        "-m",
                        whisper_model,
                        "-l",
                        LANGUAGE,
                        "--no-gpu",
                        "-nt",
                        "-np",
                        "-otxt",
                        "-of",
                        str(out_prefix),
                        "-f",
                        str(wav),
                    ]
                )
                if rc != 0:
                    return None
                text = (
                    out_prefix.with_suffix(".txt").read_text(encoding="utf-8").strip()
                )
            except (TimeoutError, OSError) as exc:
                _log("transcribe_failed", error=str(exc))
                return None
    if not text:
        _log("transcribe_empty", audio=str(audio_path))
        return None
    return text
