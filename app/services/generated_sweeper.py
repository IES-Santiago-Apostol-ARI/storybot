"""D-13: 7-day disk hygiene for content/generated/<uuid>/ directories.

Runs at FastAPI lifespan startup (no scheduler). Logs each removal as JSON to stderr.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.story_manager import StoryManager

MAX_AGE_SECONDS: int = 7 * 86400


def sweep_generated(
    story_manager: StoryManager,
    *,
    generated_dir: Path | None = None,
    max_age_seconds: int = MAX_AGE_SECONDS,
    now_seconds: float | None = None,
) -> int:
    """Remove generated story dirs older than max_age_seconds.

    Returns count of removed directories. Each removal is logged to stderr as JSON.
    """
    target_dir = (
        generated_dir if generated_dir is not None else story_manager.GENERATED_DIR
    )
    now = now_seconds if now_seconds is not None else time.time()
    removed = 0
    if not target_dir.exists():
        print(json.dumps({"event": "sweep_complete", "removed": 0}), file=sys.stderr)
        return 0
    for entry in sorted(target_dir.iterdir()):
        if not entry.is_dir():
            continue
        story_json = entry / "story.json"
        if not story_json.exists():
            # Defense-in-depth: skip dirs we don't recognise (e.g., .trash, partials).
            continue
        try:
            mtime = story_json.stat().st_mtime
        except OSError:
            continue
        age = now - mtime
        if age > max_age_seconds:
            try:
                shutil.rmtree(entry)
            except OSError as e:
                print(
                    json.dumps(
                        {
                            "event": "sweep_failed",
                            "id": entry.name,
                            "reason": type(e).__name__,
                        }
                    ),
                    file=sys.stderr,
                )
                continue
            print(
                json.dumps({"event": "sweep_removed", "id": entry.name, "age": age}),
                file=sys.stderr,
            )
            removed += 1
    print(json.dumps({"event": "sweep_complete", "removed": removed}), file=sys.stderr)
    return removed
