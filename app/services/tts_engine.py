"""Piper TTS engine service for Spanish text-to-speech."""

import json
import random
from pathlib import Path

from app.services.base import HardwareService


class TTSEngine(HardwareService):
    """Piper TTS engine for Spanish text-to-speech.

    Per CONTEXT.md, TTS is always real (never mocked) and kept loaded
    in memory (~400MB) for fast synthesis.
    """

    def __init__(self, model_path: Path | None = None) -> None:
        """Initialize TTS engine.

        Args:
            model_path: Path to Piper model directory. If None, uses default.
        """
        self._model_path = model_path
        self._voice = None
        self._config = None
        self._model_loaded = False
        self._model_name = ""
        self._length_scale: float | None = None
        self._speaker_mode = "random"

    @property
    def is_mock(self) -> bool:
        """TTS is never mocked per CONTEXT.md."""
        return False

    @property
    def is_loaded(self) -> bool:
        """Check if model is loaded in memory."""
        return self._model_loaded

    async def load_model(self, model_name: str = "es_ES-sharvard-medium") -> bool:
        """Load Piper voice model into memory.

        Args:
            model_name: Name of the model to load.

        Returns:
            True if model loaded successfully, False otherwise.
        """
        try:
            from piper import PiperVoice

            # Try to find model in common locations
            model_dir = self._model_path or Path.home() / ".local" / "share" / "piper"
            model_file = model_dir / f"{model_name}.onnx"
            config_file = model_dir / f"{model_name}.onnx.json"

            if not model_file.exists():
                # Model not found - provide helpful error message
                self._model_loaded = False
                self._model_name = model_name
                return False

            # Load the model
            self._voice = PiperVoice.load(
                model_path=str(model_file),
                config_path=str(config_file) if config_file.exists() else None,
            )
            # Keep the parsed voice config for speaker introspection
            # (num_speakers / speaker_id_map). Optional — pick_speaker
            # degrades to None without it.
            try:
                self._config = json.loads(config_file.read_text())
            except (OSError, json.JSONDecodeError):
                self._config = None
            self._model_loaded = True
            self._model_name = model_name
            return True

        except ImportError:
            # piper-tts not installed
            self._model_loaded = False
            return False
        except Exception:
            # Model load failed
            self._model_loaded = False
            return False

    def synthesize(self, text: str, speaker_id: int | None = None) -> bytes:
        """Synthesize speech from text.

        Args:
            text: Text to synthesize (should be Spanish).
            speaker_id: Speaker to use for multi-speaker models (see
                pick_speaker). None keeps the voice default.

        Returns:
            WAV audio data as bytes.

        Raises:
            RuntimeError: If model not loaded.
        """
        if not self._model_loaded or self._voice is None:
            raise RuntimeError(
                "Model not loaded. Call load_model() first. "
                "Download models from: https://github.com/rhasspy/piper/releases"
            )

        from piper import SynthesisConfig

        syn_config = SynthesisConfig(
            speaker_id=speaker_id, length_scale=self._length_scale
        )
        audio_bytes = b""
        for chunk in self._voice.synthesize(text, syn_config=syn_config):
            audio_bytes += chunk.audio_int16_bytes
        return audio_bytes

    def pick_speaker(self) -> int | None:
        """Pick the speaker id for one story.

        For multi-speaker models (sharvard: {"M": 0, "F": 1}) returns the
        configured speaker, or a random one when the mode is "random" —
        chosen once per story so the narrator stays consistent across
        segments. Returns None (voice default) for single-speaker models,
        unknown modes, or when no config is available.
        """
        if not self._model_loaded or not isinstance(self._config, dict):
            return None
        id_map = self._config.get("speaker_id_map") or {}
        num_speakers = self._config.get("num_speakers") or len(id_map) or 1
        if num_speakers <= 1:
            return None
        if self._speaker_mode in id_map:
            return id_map[self._speaker_mode]
        if self._speaker_mode == "random":
            ids = sorted(id_map.values()) or list(range(num_speakers))
            return random.choice(ids)
        return None

    async def synthesize_to_file(self, text: str, output_path: Path) -> None:
        """Synthesize speech and write to WAV file.

        Args:
            text: Text to synthesize.
            output_path: Path where WAV file will be written.

        Raises:
            RuntimeError: If model not loaded.
        """
        if not self._model_loaded or self._voice is None:
            raise RuntimeError(
                "Model not loaded. Call load_model() first. "
                "Download models from: https://github.com/rhasspy/piper/releases"
            )

        import wave

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with wave.open(str(output_path), "wb") as wav_file:
            self._voice.synthesize_wav(text, wav_file)

    async def get_status(self) -> dict:
        """Get TTS engine status.

        Returns:
            dict with status information.
        """
        if self._model_loaded:
            status_val = "ok"
            error_msg = None
        else:
            status_val = "error"
            error_msg = (
                f"Model '{self._model_name}' not loaded. "
                f"Download from https://github.com/rhasspy/piper/releases"
            )

        return {
            "name": "tts",
            "is_mock": self.is_mock,
            "status": status_val,
            "error_message": error_msg,
        }

    async def initialize(
        self,
        model_name: str = "es_ES-sharvard-medium",
        length_scale: float | None = None,
        speaker: str = "random",
    ) -> None:
        """Initialize TTS engine (loads the given voice model).

        Args:
            model_name: Piper voice model to load.
            length_scale: Phoneme-duration multiplier (>1 = slower).
                None keeps the voice default.
            speaker: "random" | speaker_id_map key ("M"/"F" for sharvard).
        """
        self._length_scale = length_scale
        self._speaker_mode = speaker
        await self.load_model(model_name=model_name)

    async def shutdown(self) -> None:
        """Shutdown TTS engine and free memory."""
        self._voice = None
        self._config = None
        self._model_loaded = False
