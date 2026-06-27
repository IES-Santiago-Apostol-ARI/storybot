"""Audio player service for WAV and MP3 playback."""

import asyncio
from pathlib import Path

from app.services.base import HardwareService


class AudioPlayer(HardwareService):
    """Base audio player protocol."""

    @property
    def is_mock(self) -> bool:
        """Return True if this is a mock player."""
        ...

    async def play(self, file_path: Path) -> None:
        """Play audio file.

        Args:
            file_path: Path to audio file (WAV or MP3).
        """
        ...

    async def stop(self) -> None:
        """Stop current playback."""
        ...

    @property
    def is_playing(self) -> bool:
        """Check if audio is currently playing."""
        ...


class RealAudioPlayer(AudioPlayer):
    """Real audio player using simpleaudio and pydub."""

    def __init__(self) -> None:
        """Initialize real audio player."""
        self._playback_obj: object | None = None
        self._playing = False
        self._available = self._check_availability()

    @property
    def is_mock(self) -> bool:
        """Return False - this is real audio player."""
        return False

    def _check_availability(self) -> bool:
        """Check if audio system is available."""
        try:
            import simpleaudio as sa

            return True
        except (ImportError, OSError):
            return False

    async def play(self, file_path: Path) -> None:
        """Play audio file (WAV or MP3).

        Args:
            file_path: Path to audio file.
        """
        if not self._available:
            raise RuntimeError("Audio system not available")

        file_path = Path(file_path)

        # Convert MP3 to WAV if needed
        if file_path.suffix.lower() == ".mp3":
            file_path = await self._convert_mp3_to_wav(file_path)

        # Play WAV file
        try:
            import simpleaudio as sa

            wave_obj = sa.WaveObject.from_wave_file(str(file_path))
            self._playback_obj = wave_obj.play()
            self._playing = True

            # Wait for playback to complete in background
            asyncio.create_task(self._wait_for_completion())

        except Exception as e:
            self._playing = False
            raise RuntimeError(f"Failed to play audio: {e}") from e

    async def _convert_mp3_to_wav(self, mp3_path: Path) -> Path:
        """Convert MP3 to WAV using pydub.

        Args:
            mp3_path: Path to MP3 file.

        Returns:
            Path to converted WAV file.
        """
        try:
            from pydub import AudioSegment

            wav_path = mp3_path.with_suffix(".wav")
            audio = AudioSegment.from_mp3(str(mp3_path))
            audio.export(str(wav_path), format="wav")
            return wav_path

        except ImportError as e:
            raise RuntimeError("pydub not installed - required for MP3 playback") from e
        except Exception as e:
            raise RuntimeError(f"Failed to convert MP3: {e}") from e

    async def _wait_for_completion(self) -> None:
        """Wait for playback to complete."""
        # Snapshot the handle: a concurrent stop() sets self._playback_obj to
        # None, so reading the attribute inside the loop would raise
        # AttributeError on None (a use-after-free style crash). The local keeps
        # a stable reference; stop() calls .stop() on it, so is_playing() flips
        # to False and the loop exits cleanly.
        playback_obj = self._playback_obj
        if playback_obj is not None:
            while playback_obj.is_playing():
                await asyncio.sleep(0.1)
            self._playing = False

    async def stop(self) -> None:
        """Stop current playback."""
        if self._playback_obj is not None:
            try:
                self._playback_obj.stop()
            except Exception:
                pass
        self._playing = False
        self._playback_obj = None

    @property
    def is_playing(self) -> bool:
        """Check if audio is currently playing."""
        return self._playing

    async def get_status(self) -> dict:
        """Get audio player status."""
        if not self._available:
            return {
                "name": "audio",
                "is_mock": False,
                "status": "not_connected",
                "error_message": "Audio system not available",
            }

        return {
            "name": "audio",
            "is_mock": self.is_mock,
            "status": "ok",
            "error_message": None,
        }

    async def initialize(self) -> None:
        """Initialize audio player."""
        self._available = self._check_availability()

    async def shutdown(self) -> None:
        """Shutdown audio player."""
        await self.stop()


class MockAudioPlayer(AudioPlayer):
    """Mock audio player for testing without audio hardware."""

    def __init__(self) -> None:
        """Initialize mock audio player."""
        self._playing = False
        self._current_file: Path | None = None

    @property
    def is_mock(self) -> bool:
        """Return True - this is mock audio player."""
        return True

    async def play(self, file_path: Path) -> None:
        """Simulate playing audio file.

        Args:
            file_path: Path to audio file (for tracking only).
        """
        self._current_file = Path(file_path)
        self._playing = True

        # Simulate playback ending after a short time
        asyncio.create_task(self._simulate_playback_end())

    async def _simulate_playback_end(self) -> None:
        """Simulate playback ending."""
        await asyncio.sleep(0.5)  # Simulate short playback
        self._playing = False

    async def stop(self) -> None:
        """Stop simulated playback."""
        self._playing = False
        self._current_file = None

    @property
    def is_playing(self) -> bool:
        """Check if audio is 'playing'."""
        return self._playing

    async def get_status(self) -> dict:
        """Get mock audio player status."""
        return {
            "name": "audio",
            "is_mock": self.is_mock,
            "status": "ok",
            "error_message": None,
        }

    async def initialize(self) -> None:
        """Initialize mock audio player."""
        self._playing = False

    async def shutdown(self) -> None:
        """Shutdown mock audio player."""
        await self.stop()


def create_audio_player() -> AudioPlayer:
    """Create appropriate audio player based on hardware availability.

    Returns:
        RealAudioPlayer if audio system available, else MockAudioPlayer.
    """
    # Try real first
    real_player = RealAudioPlayer()
    if real_player._available:
        return real_player
    return MockAudioPlayer()
