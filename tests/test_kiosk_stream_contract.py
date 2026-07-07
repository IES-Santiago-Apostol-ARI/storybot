"""Kiosk generation-stream contract source assertions (IMPROVEMENTS.md 1.1).

The backend emits the {"text": null, "done": true} sentinel BEFORE the flushed
tail's audio_ready and long before cover_ready/cover_failed (cover generation
takes 60-120 s). The kiosk must therefore never treat that sentinel as
end-of-stream: it marks its playback queue complete on the explicit
{"audio_complete": true} event and keeps reading until the server closes.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT_PATH = Path("static/children/script.js")


@pytest.fixture(scope="module")
def script_text():
    """Read the kiosk script once per module."""
    return SCRIPT_PATH.read_text(encoding="utf-8")


class TestGenerationStreamContract:
    def test_handles_audio_complete_event(self, script_text):
        assert "audio_complete" in script_text, (
            "script.js must markStreamComplete on the explicit audio_complete "
            "event from /api/generate/story"
        )

    def test_no_early_return_on_story_sentinel(self, script_text):
        assert "event.text === null && event.done === true" not in script_text, (
            'the {"text": null, "done": true} sentinel must not terminate the '
            "read loop — the flushed tail audio_ready and cover_ready arrive "
            "after it"
        )


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_script_js_parses():
    """Guard against syntax slips in the hand-edited kiosk script."""
    subprocess.run(["node", "--check", str(SCRIPT_PATH)], check=True)
