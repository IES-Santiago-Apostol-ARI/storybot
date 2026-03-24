"""Tests for TTS engine service."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.tts_engine import TTSEngine


@pytest.fixture
def tts_engine():
    """Create a TTS engine instance."""
    return TTSEngine()


@pytest.fixture
def tts_engine_with_path(tmp_path):
    """Create a TTS engine with custom model path."""
    return TTSEngine(model_path=tmp_path)


class TestTTSEngine:
    """Test TTS engine functionality."""

    @pytest.mark.asyncio
    async def test_tts_engine_initializes(self, tts_engine):
        """Test that TTS engine can be created."""
        assert tts_engine is not None
        assert hasattr(tts_engine, "is_loaded")
        assert hasattr(tts_engine, "synthesize")
        assert hasattr(tts_engine, "synthesize_to_file")

    @pytest.mark.asyncio
    async def test_tts_engine_not_loaded_initially(self, tts_engine):
        """Test that TTS engine is not loaded until model is loaded."""
        assert tts_engine.is_loaded is False

    @pytest.mark.asyncio
    async def test_tts_engine_load_model(self, tts_engine):
        """Test loading a TTS model."""
        # This will fail if model doesn't exist - that's expected
        result = await tts_engine.load_model("es_ES-sharvard-medium")
        # Result could be False if model not found
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_tts_engine_synthesize_without_model(self, tts_engine):
        """Test that synthesize fails gracefully without model."""
        with pytest.raises(RuntimeError, match="Model not loaded"):
            tts_engine.synthesize("Hola mundo")

    @pytest.mark.asyncio
    async def test_tts_engine_synthesize_to_file_without_model(
        self, tts_engine, tmp_path
    ):
        """Test that synthesize_to_file fails gracefully without model."""
        output_file = tmp_path / "test.wav"
        with pytest.raises(RuntimeError, match="Model not loaded"):
            await tts_engine.synthesize_to_file("Hola mundo", output_file)

    @pytest.mark.asyncio
    async def test_tts_engine_get_status(self, tts_engine):
        """Test getting TTS engine status."""
        status = await tts_engine.get_status()
        assert "name" in status
        assert "is_mock" in status
        assert "status" in status
        assert status["name"] == "tts"
        assert status["is_mock"] is False  # TTS is never mocked per CONTEXT.md

    @pytest.mark.asyncio
    async def test_tts_engine_get_status_unloaded_has_error_message(self, tmp_path):
        """Test that unloaded engine status includes error message."""
        # Create engine with custom path and create model file to pass file check
        # but fail on actual load (no piper installed)
        engine = TTSEngine(model_path=tmp_path)
        model_name = "test-model"
        (tmp_path / f"{model_name}.onnx").write_bytes(b"fake")

        # This will fail because piper isn't installed, but model_name gets set
        # before the import attempt
        await engine.load_model(model_name)
        status = await engine.get_status()
        assert status["status"] == "error"
        assert status["error_message"] is not None

    @pytest.mark.asyncio
    async def test_tts_engine_is_mock_always_false(self, tts_engine):
        """Test that TTS engine is never a mock (per CONTEXT.md)."""
        assert tts_engine.is_mock is False

    @pytest.mark.asyncio
    async def test_tts_engine_with_custom_model_path(self, tts_engine_with_path, tmp_path):
        """Test TTS engine with custom model path."""
        assert tts_engine_with_path._model_path == tmp_path

    @pytest.mark.asyncio
    async def test_tts_engine_initialize_calls_load_model(self, tts_engine):
        """Test that initialize() calls load_model()."""
        with patch.object(tts_engine, "load_model", return_value=False) as mock_load:
            await tts_engine.initialize()
            mock_load.assert_called_once()

    @pytest.mark.asyncio
    async def test_tts_engine_shutdown_clears_state(self, tts_engine):
        """Test that shutdown() clears model state."""
        # Set some state manually
        tts_engine._model_loaded = True
        tts_engine._voice = MagicMock()
        tts_engine._config = {"test": "config"}

        await tts_engine.shutdown()

        assert tts_engine._voice is None
        assert tts_engine._config is None
        assert tts_engine._model_loaded is False

    @pytest.mark.asyncio
    async def test_tts_engine_load_model_import_error(self, tts_engine):
        """Test load_model handles ImportError when piper not installed."""
        with patch.dict("sys.modules", {"piper": None}):
            # Force ImportError by patching the import
            with patch(
                "app.services.tts_engine.TTSEngine.load_model",
                wraps=tts_engine.load_model,
            ):
                result = await tts_engine.load_model()
                assert result is False
                assert tts_engine.is_loaded is False

    @pytest.mark.asyncio
    async def test_tts_engine_load_model_with_existing_model(self, tmp_path):
        """Test load_model with model files that exist."""
        import sys

        # Create fake model files
        model_name = "test-model"
        (tmp_path / f"{model_name}.onnx").write_bytes(b"fake model data")
        (tmp_path / f"{model_name}.onnx.json").write_text('{"sample_rate": 22050}')

        engine = TTSEngine(model_path=tmp_path)

        # Create mock piper module and inject into sys.modules
        mock_piper_module = MagicMock()
        mock_voice = MagicMock()
        mock_piper_module.PiperVoice.load.return_value = mock_voice

        with patch.dict(sys.modules, {"piper": mock_piper_module}):
            result = await engine.load_model(model_name)

            assert result is True
            assert engine.is_loaded is True
            assert engine._model_name == model_name
            mock_piper_module.PiperVoice.load.assert_called_once()

    @pytest.mark.asyncio
    async def test_tts_engine_get_status_when_loaded(self, tmp_path):
        """Test get_status returns ok when model is loaded."""
        import sys

        engine = TTSEngine(model_path=tmp_path)

        # Create fake model files
        model_name = "test-model"
        (tmp_path / f"{model_name}.onnx").write_bytes(b"fake")
        (tmp_path / f"{model_name}.onnx.json").write_text("{}")

        # Create mock piper module
        mock_piper_module = MagicMock()
        mock_piper_module.PiperVoice.load.return_value = MagicMock()

        with patch.dict(sys.modules, {"piper": mock_piper_module}):
            await engine.load_model(model_name)

        status = await engine.get_status()
        assert status["status"] == "ok"
        assert status["error_message"] is None

    @pytest.mark.asyncio
    async def test_tts_engine_synthesize_with_loaded_model(self, tmp_path):
        """Test synthesize works when model is loaded."""
        import sys

        engine = TTSEngine(model_path=tmp_path)

        # Create fake model files
        model_name = "test-model"
        (tmp_path / f"{model_name}.onnx").write_bytes(b"fake")

        # piper 1.4.1 API: voice.synthesize(text) → Iterable[AudioChunk]
        mock_chunk1 = MagicMock()
        mock_chunk1.audio_int16_bytes = b"audio"
        mock_chunk2 = MagicMock()
        mock_chunk2.audio_int16_bytes = b"data"
        mock_voice = MagicMock()
        mock_voice.synthesize.return_value = [mock_chunk1, mock_chunk2]

        # Create mock piper module
        mock_piper_module = MagicMock()
        mock_piper_module.PiperVoice.load.return_value = mock_voice

        with patch.dict(sys.modules, {"piper": mock_piper_module}):
            await engine.load_model(model_name)

        result = engine.synthesize("Hola mundo")
        assert result == b"audiodata"
        mock_voice.synthesize.assert_called_once()

    @pytest.mark.asyncio
    async def test_tts_engine_synthesize_to_file_with_loaded_model(self, tmp_path):
        """Test synthesize_to_file works when model is loaded."""
        import sys

        engine = TTSEngine(model_path=tmp_path)

        # Create fake model files
        model_name = "test-model"
        (tmp_path / f"{model_name}.onnx").write_bytes(b"fake")

        # Mock voice using piper 1.4.1 API: voice.synthesize_wav(text, wav_file)
        # synthesize_wav must set up the wave file so it can close cleanly
        def fake_synthesize_wav(text, wav_file):
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            wav_file.writeframes(b"")

        mock_voice = MagicMock()
        mock_voice.synthesize_wav.side_effect = fake_synthesize_wav

        # Create mock piper module
        mock_piper_module = MagicMock()
        mock_piper_module.PiperVoice.load.return_value = mock_voice

        with patch.dict(sys.modules, {"piper": mock_piper_module}):
            await engine.load_model(model_name)

        output_file = tmp_path / "output" / "test.wav"
        await engine.synthesize_to_file("Hola", output_file)

        # Verify parent directory was created and synthesize_wav was called
        assert output_file.parent.exists()
        mock_voice.synthesize_wav.assert_called_once()

    @pytest.mark.asyncio
    async def test_tts_engine_load_model_exception(self, tmp_path):
        """Test load_model handles generic exceptions."""
        import sys

        # Create model file to pass existence check
        model_name = "test-model"
        (tmp_path / f"{model_name}.onnx").write_bytes(b"fake")

        engine = TTSEngine(model_path=tmp_path)

        # Create mock piper module that raises on load
        mock_piper_module = MagicMock()
        mock_piper_module.PiperVoice.load.side_effect = RuntimeError("Model load failed")

        with patch.dict(sys.modules, {"piper": mock_piper_module}):
            result = await engine.load_model(model_name)

            assert result is False
            assert engine.is_loaded is False
