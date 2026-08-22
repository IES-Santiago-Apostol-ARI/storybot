"""Tests for audio player service."""

import asyncio
import contextlib
import importlib.machinery
import sys
import types
from pathlib import Path

import pytest

from app.services.audio_player import MockAudioPlayer, RealAudioPlayer


@pytest.fixture
def mock_audio_player():
    """Create a mock audio player for testing."""
    return MockAudioPlayer()


class TestMockAudioPlayer:
    """Test mock audio player functionality."""

    @pytest.mark.asyncio
    async def test_mock_audio_player_initializes(self, mock_audio_player):
        """Test that mock audio player can be created."""
        assert mock_audio_player is not None
        assert hasattr(mock_audio_player, "is_mock")
        assert hasattr(mock_audio_player, "play")
        assert hasattr(mock_audio_player, "stop")
        assert hasattr(mock_audio_player, "is_playing")

    @pytest.mark.asyncio
    async def test_mock_audio_player_is_mock(self, mock_audio_player):
        """Test that mock audio player reports as mock."""
        assert mock_audio_player.is_mock is True

    @pytest.mark.asyncio
    async def test_mock_audio_player_not_playing_initially(self, mock_audio_player):
        """Test that mock audio player is not playing initially."""
        assert mock_audio_player.is_playing is False

    @pytest.mark.asyncio
    async def test_mock_audio_player_play_wav(self, mock_audio_player, tmp_path):
        """Test playing a WAV file with mock player."""
        # Create a dummy WAV file (minimal valid WAV header)
        wav_file = tmp_path / "test.wav"
        wav_file.write_bytes(
            b"RIFF\x24\x00\x00\x00WAVEfmt "
            b"\x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00\x88\x58\x01\x00"
            b"\x02\x00\x10\x00data\x00\x00\x00\x00"
        )

        await mock_audio_player.play(wav_file)
        assert mock_audio_player.is_playing is True

    @pytest.mark.asyncio
    async def test_mock_audio_player_play_mp3(self, mock_audio_player, tmp_path):
        """Test playing an MP3 file with mock player (converts to WAV)."""
        # Create a dummy MP3 file (minimal valid MP3 header)
        mp3_file = tmp_path / "test.mp3"
        mp3_file.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 100)

        await mock_audio_player.play(mp3_file)
        # Mock player should track this even without real audio
        assert mock_audio_player.is_playing is True

    @pytest.mark.asyncio
    async def test_mock_audio_player_stop(self, mock_audio_player, tmp_path):
        """Test stopping playback."""
        wav_file = tmp_path / "test.wav"
        wav_file.write_bytes(
            b"RIFF\x24\x00\x00\x00WAVEfmt "
            b"\x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00\x88\x58\x01\x00"
            b"\x02\x00\x10\x00data\x00\x00\x00\x00"
        )

        await mock_audio_player.play(wav_file)
        assert mock_audio_player.is_playing is True

        await mock_audio_player.stop()
        assert mock_audio_player.is_playing is False

    @pytest.mark.asyncio
    async def test_stale_end_task_does_not_kill_new_playback(
        self, mock_audio_player, tmp_path
    ):
        """A new play() must survive the previous playback's end task."""
        wav_file = tmp_path / "test.wav"
        wav_file.write_bytes(
            b"RIFF\x24\x00\x00\x00WAVEfmt "
            b"\x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00\x88\x58\x01\x00"
            b"\x02\x00\x10\x00data\x00\x00\x00\x00"
        )

        await mock_audio_player.play(wav_file)
        await asyncio.sleep(0.1)
        await mock_audio_player.play(wav_file)
        # The first play's stale end-task fires 0.5 s after it started (t=0.5);
        # the second playback ends naturally 0.5 s after it started (t=0.6).
        # Check inside that window so we assert the stale task did not kill the
        # new playback, not that the new playback already finished.
        await asyncio.sleep(0.45)
        assert mock_audio_player.is_playing is True

    @pytest.mark.asyncio
    async def test_mock_audio_player_get_status(self, mock_audio_player):
        """Test getting mock audio player status."""
        status = await mock_audio_player.get_status()
        assert "name" in status
        assert "is_mock" in status
        assert "status" in status
        assert status["name"] == "audio"
        assert status["is_mock"] is True

    @pytest.mark.asyncio
    async def test_mock_audio_player_initialize_and_shutdown(self, mock_audio_player):
        """Test initialize and shutdown methods."""
        await mock_audio_player.initialize()
        await mock_audio_player.shutdown()
        assert mock_audio_player.is_playing is False


class _FakePlayback:
    """Minimal simpleaudio PlayObject stand-in: is_playing()/stop()."""

    def __init__(self) -> None:
        self._playing = True

    def is_playing(self) -> bool:
        return self._playing

    def stop(self) -> None:
        self._playing = False


class TestRealAudioPlayerStopRace:
    """Regression: stop() must not crash an in-flight _wait_for_completion."""

    @pytest.mark.asyncio
    async def test_stop_during_wait_does_not_raise(self):
        player = RealAudioPlayer()
        player._available = True
        fake = _FakePlayback()
        player._playback_obj = fake
        player._playing = True

        wait_task = asyncio.create_task(player._wait_for_completion())
        await asyncio.sleep(0)  # let the wait loop start reading the handle

        # stop() nulls self._playback_obj while the wait loop is running. Before
        # the snapshot fix this caused AttributeError on None inside the loop.
        await player.stop()

        await asyncio.wait_for(wait_task, timeout=1.0)
        assert player.is_playing is False


class TestRealAudioPlayer:
    """play() must stop previous playback and keep the wait task reachable."""

    @pytest.fixture
    def fake_simpleaudio(self, monkeypatch):
        """Install a fake simpleaudio module and return the created playbacks."""
        created: list[_FakePlayback] = []

        class _FakeWaveObject:
            @classmethod
            def from_wave_file(cls, path):
                return cls()

            def play(self):
                playback = _FakePlayback()
                created.append(playback)
                return playback

        module = types.ModuleType("simpleaudio")
        module.__spec__ = importlib.machinery.ModuleSpec("simpleaudio", loader=None)
        setattr(module, "WaveObject", _FakeWaveObject)
        monkeypatch.setitem(sys.modules, "simpleaudio", module)
        return created

    @staticmethod
    def _make_wav(tmp_path) -> Path:
        wav_file = tmp_path / "test.wav"
        wav_file.write_bytes(
            b"RIFF\x24\x00\x00\x00WAVEfmt "
            b"\x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00\x88\x58\x01\x00"
            b"\x02\x00\x10\x00data\x00\x00\x00\x00"
        )
        return wav_file

    @pytest.mark.asyncio
    async def test_play_stops_previous_playback(self, tmp_path, fake_simpleaudio):
        """A second play() must stop the first playback object."""
        player = RealAudioPlayer()
        player._available = True
        wav_file = self._make_wav(tmp_path)

        await player.play(wav_file)
        await player.play(wav_file)

        assert fake_simpleaudio[0]._playing is False

    @pytest.mark.asyncio
    async def test_stop_cancels_wait_task(self, tmp_path, fake_simpleaudio):
        """stop() must cancel the background wait task and clear its ref."""
        player = RealAudioPlayer()
        player._available = True
        wav_file = self._make_wav(tmp_path)

        await player.play(wav_file)
        assert player._wait_task is not None
        wait_task = player._wait_task

        await player.stop()

        assert player._wait_task is None
        with contextlib.suppress(asyncio.CancelledError):
            await wait_task
        assert wait_task.cancelled()
