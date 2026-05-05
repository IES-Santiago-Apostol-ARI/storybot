"""Wave 0 RED stub for bridge audio asset presence (D-04, D-05).

Plan 16-01 turns these GREEN by rendering 3-5 .wav files via Piper.
"""

import wave
from pathlib import Path

import pytest

BRIDGE_DIR = Path("static/children/assets/bridge")


def test_bridge_dir_exists():
    assert BRIDGE_DIR.is_dir(), "Plan 16-01 must create static/children/assets/bridge/"


def test_bridge_files_count_in_range():
    files = sorted(BRIDGE_DIR.glob("*.wav"))
    assert 3 <= len(files) <= 5, f"D-04 requires 3-5 bridge clips, found {len(files)}"


@pytest.mark.parametrize("idx", range(5))
def test_bridge_file_is_valid_wav_when_present(idx):
    wav = BRIDGE_DIR / f"{idx:02d}.wav"
    if not wav.exists():
        pytest.skip(f"{wav.name} not rendered (max 5 clips)")
    with wave.open(str(wav), "rb") as wf:
        assert wf.getnframes() > 0
        assert wf.getnchannels() == 1, "Piper output must be mono"
        duration = wf.getnframes() / wf.getframerate()
        assert duration <= 3.5, f"D-04 discretion: clip {idx} should be ≤ 3.0s (3.5s slack), got {duration:.2f}s"
