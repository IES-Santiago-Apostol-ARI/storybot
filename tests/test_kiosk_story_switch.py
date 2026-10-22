"""A new story card replaces the story on screen.

The kiosk used to ignore story cards unless it was idle. A paused story sat on
screen, the reader beeped on every other card, and nothing started: to a
child (and to the adult debugging it) the robot looked broken. Runs the real
script.js in Node, see tests/kiosk_harness/README.md.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HARNESS_DIR = Path(__file__).parent / "kiosk_harness"
SCENARIO = HARNESS_DIR / "scenario_story_switch.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is required to execute the kiosk JS"
)


@pytest.fixture(scope="module")
def result() -> dict:
    proc = subprocess.run(
        ["node", str(SCENARIO)],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=HARNESS_DIR,
    )
    assert proc.returncode == 0, f"harness failed:\n{proc.stderr}"
    last = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")][-1]
    return json.loads(last)


def test_retapping_the_same_card_still_pauses(result):
    assert result["pausedA"] == {"state": "playing", "story": "story-a", "paused": True}


def test_new_card_replaces_a_paused_story(result):
    assert result["afterSwitch"] == {
        "state": "playing",
        "story": "story-b",
        "paused": False,
    }


def test_new_card_on_thankyou_survives_the_idle_timer(result):
    assert result["afterThankyou"] == {
        "state": "playing",
        "story": "story-a",
        "paused": False,
    }
