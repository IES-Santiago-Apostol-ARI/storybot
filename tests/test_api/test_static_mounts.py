"""Static content mounts must exist on a fresh install (IMPROVEMENTS.md 1.2).

app.main decides its mounts at import time. On a fresh install nothing has
created content/generated yet (deploy/install.sh only creates stories/,
interactive/, images/), so a conditional mount silently disappears and the
first generated story's audio/cover URLs 404 until the service restarts.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_content_mounts_exist_without_content_dirs(tmp_path):
    """Importing the app from a cwd with no content/ still mounts both
    /static/stories and /static/generated."""
    code = (
        "import json\n"
        "from app.main import app\n"
        "names = [getattr(r, 'name', None) for r in app.routes]\n"
        "print(json.dumps(names))\n"
    )
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "PYTHONPATH": str(REPO_ROOT),
        "TESTING": "1",
    }
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    names = json.loads(result.stdout.strip().splitlines()[-1])
    assert "stories" in names, f"/static/stories not mounted; mounts: {names}"
    assert "generated" in names, f"/static/generated not mounted; mounts: {names}"
