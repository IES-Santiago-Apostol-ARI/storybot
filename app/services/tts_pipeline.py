"""TTSPipeline — sentence to WAV segment persistence."""

import asyncio
import wave
from pathlib import Path


class TTSPipeline:
    """Orchestrates sentence → synthesizer → WAV file persistence.

    The synthesizer is duck-typed: any object with ``synthesize(text) -> bytes``
    returning raw PCM int16 data at 22050Hz mono.
    """

    def __init__(self, synthesizer) -> None:
        self._synth = synthesizer

    async def synthesize_segment(
        self, text: str, out_dir: Path, index: int
    ) -> dict:
        audio_dir = out_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{index:03d}.wav"
        wav_path = audio_dir / filename

        try:
            pcm_bytes = await asyncio.to_thread(self._synth.synthesize, text)
            # Write to temp then rename to avoid partial files
            tmp_path = wav_path.with_suffix(".tmp")
            with wave.open(str(tmp_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(22050)
                wf.writeframes(pcm_bytes)
            tmp_path.rename(wav_path)
        except Exception as exc:
            # Remove tmp file if it exists
            tmp_path = wav_path.with_suffix(".tmp")
            if tmp_path.exists():
                tmp_path.unlink()
            return {"index": index, "text": text, "error": str(exc), "audio": None}

        return {"index": index, "text": text, "audio": f"audio/{filename}"}
