"""TTSPipeline — sentence to WAV segment persistence."""

import asyncio
import wave
from pathlib import Path


class TTSPipeline:
    """Orchestrates sentence → synthesizer → WAV file persistence.

    The synthesizer is duck-typed: any object with ``synthesize(text) -> bytes``
    returning raw PCM int16 data at 22050Hz mono. Multi-speaker synthesizers
    may additionally accept ``synthesize(text, speaker_id)`` and expose
    ``pick_speaker() -> int | None`` (see TTSEngine).
    """

    def __init__(self, synthesizer) -> None:
        self._synth = synthesizer

    def pick_speaker(self) -> int | None:
        """Pick a per-story speaker via the synthesizer, if it supports it."""
        picker = getattr(self._synth, "pick_speaker", None)
        return picker() if callable(picker) else None

    async def synthesize_segment(
        self, text: str, out_dir: Path, index: int, speaker_id: int | None = None
    ) -> dict:
        audio_dir = out_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{index:03d}.wav"
        wav_path = audio_dir / filename

        try:
            # Only forward speaker_id when set so plain synthesize(text)
            # synthesizers keep working.
            if speaker_id is None:
                pcm_bytes = await asyncio.to_thread(self._synth.synthesize, text)
            else:
                pcm_bytes = await asyncio.to_thread(
                    self._synth.synthesize, text, speaker_id
                )
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
