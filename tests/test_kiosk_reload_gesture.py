"""The kiosk's hidden reload gesture.

Firefox --kiosk offers no way to reload the page from the touchscreen, so
script.js reloads when a finger is held still on the top-left corner. It must
fire for that hold and nothing else: a child tapping or swiping across the
corner must never reload the kiosk mid-story.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HARNESS_DIR = Path(__file__).parent / "kiosk_harness"
SCENARIO = HARNESS_DIR / "scenario_reload_gesture.js"

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


def test_holding_the_corner_reloads_once(result):
    assert result["heldInCorner"] == 1


@pytest.mark.parametrize(
    "case",
    [
        "releasedEarly",
        "startedOutsideCorner",
        "draggedOutOfCorner",
        "cancelledByBrowser",
    ],
)
def test_anything_short_of_a_full_hold_does_not_reload(result, case):
    assert result[case] == 0


def test_a_second_finger_elsewhere_does_not_cancel_the_hold(result):
    assert result["otherFingerLiftedElsewhere"] == 1
