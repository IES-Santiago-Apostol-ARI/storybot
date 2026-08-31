"""The GO card must survive an interrupted generation.

`_generationActive` guards startGeneration against re-entry, but it was only
released from `generationAudioQueue.onComplete`. A generation that never got
there — the child taps a pre-recorded story mid-generation, or presses the
interrupt button — left the flag stuck true, and every later GO card returned
on the guard. The kiosk still drew the parameter chips and still cleared them,
so it looked alive while being unable to generate anything ever again.

Unlike tests/test_kiosk_param_toggle.py (regex assertions over the source),
this executes the real script.js in Node, which is what it takes to catch a
bug that only shows up across several card taps.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

HARNESS_DIR = Path(__file__).parent / "kiosk_harness"
SCENARIO = HARNESS_DIR / "scenario_interrupted_generation.js"

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


def test_chips_are_collected_after_the_interruption(result):
    """The GO card must receive a non-empty collection.

    Two chips: the one D-09 restores when the kiosk drops back to idle, plus
    the freshly tapped one.
    """
    assert result["chipsBeforeGo"] == 2


def test_go_generates_again_after_an_interrupted_generation(result):
    """Two GO taps, two generations — the first must not wedge the second."""
    assert result["posts"] == 2, (
        "the GO card produced no second POST /api/generate/story: "
        "_generationActive was never released when the generation was cut short"
    )
