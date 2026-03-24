"""Piper TTS engine service for Spanish text-to-speech."""

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

    def synthesize(self, text: str) -> bytes:
        """Synthesize speech from text.

        Args:
            text: Text to synthesize (should be Spanish).

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

        audio_bytes = b""
        for chunk in self._voice.synthesize(text):
            audio_bytes += chunk.audio_int16_bytes
        return audio_bytes

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

    async def initialize(self) -> None:
        """Initialize TTS engine (loads default model)."""
        await self.load_model()

    async def shutdown(self) -> None:
        """Shutdown TTS engine and free memory."""
        self._voice = None
        self._config = None
        self._model_loaded = False
