#!/usr/bin/env python3
"""Phase 16 D-04 / D-05 — pre-render the 5 Spanish bridge phrases to WAV.

Run once at install / build time:
    uv run python scripts/render_bridge_audio.py

The output WAVs are committed to the repo so fresh dev clones do not need to
download the Piper voice just to ship bridge clips. Re-run only if the voice
changes.
"""

from __future__ import annotations

import wave
from pathlib import Path

from piper import PiperVoice

# --- Frozen Piper config (matches app/services/tts_engine.py:37) ---
VOICE_NAME = "es_ES-sharvard-medium"
MODEL_DIR = Path.home() / ".local" / "share" / "piper"

BRIDGE_DIR = Path("static/children/assets/bridge")

# D-04: hard-coded 5 phrases, picked at random per generation by the kiosk.
BRIDGE_PHRASES: list[str] = [
    "Mmm, déjame pensar…",
    "A ver, a ver…",
    "¿Qué cuento te cuento hoy?",
    "Ya casi lo tengo…",
    "Dame un segundito…",
]


def main() -> None:
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)

    model_file = MODEL_DIR / f"{VOICE_NAME}.onnx"
    config_file = MODEL_DIR / f"{VOICE_NAME}.onnx.json"

    voice = PiperVoice.load(
        model_path=str(model_file),
        config_path=str(config_file) if config_file.exists() else None,
    )

    for idx, phrase in enumerate(BRIDGE_PHRASES):
        out = BRIDGE_DIR / f"{idx:02d}.wav"
        with wave.open(str(out), "wb") as wf:
            voice.synthesize_wav(phrase, wf)
        print(f"wrote {out} ({phrase!r})")


if __name__ == "__main__":
    main()
