"""D-13: 7-day disk hygiene for content/generated/<uuid>/ directories, plus the
matching reap of content/stories/<uuid>/ dirs the index no longer references.

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

# The only filenames a cover-only dir may contain (written by the GPIO image
# button / SD worker). A dir holding anything else is left alone.
COVER_FILENAMES: frozenset[str] = frozenset({"cover-preview.png", "cover-print.png"})


def _newest_mtime(entry: Path) -> float | None:
    """Most recent mtime among a dir's direct children, or None if unreadable."""
    newest: float | None = None
    try:
        for child in entry.iterdir():
            m = child.stat().st_mtime
            if newest is None or m > newest:
                newest = m
    except OSError:
        return None
    return newest


def _indexed_story_ids(story_manager: StoryManager) -> set[str]:
    """Story ids in the curated index, or an empty set if it can't be read."""
    try:
        return set(story_manager._load_index().get("stories", {}))
    except (OSError, ValueError):
        return set()


def _is_cover_only(entry: Path) -> bool:
    """True if the dir holds nothing but the SD worker's cover PNGs."""
    try:
        children = list(entry.iterdir())
    except OSError:
        return False
    if not children:
        return False
    return all(c.is_file() and c.name in COVER_FILENAMES for c in children)


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
    indexed: set[str] | None = None  # curated story ids, loaded on first need
    for entry in sorted(target_dir.iterdir()):
        if not entry.is_dir():
            continue
        story_json = entry / "story.json"
        if story_json.exists():
            kind = "generated"
            try:
                mtime: float | None = story_json.stat().st_mtime
            except OSError:
                continue
        else:
            # Cover-only dirs: the GPIO image button writes cover PNGs into
            # content/generated/<story_id>/ for curated stories too, so those
            # dirs never get a story.json. Reap one only when it is stale AND
            # no curated story still owns it — a live story's cover is what the
            # kiosk shows and the print button prints. Anything else we don't
            # recognise (e.g. .trash, partials) is still skipped outright.
            if not _is_cover_only(entry):
                continue
            if indexed is None:
                indexed = _indexed_story_ids(story_manager)
            # An unreadable or empty index makes every cover look unreferenced;
            # without it we cannot tell a live cover from a dead one, so keep
            # them all. The story.json branch above is unaffected.
            if not indexed or entry.name in indexed:
                continue
            kind = "cover_only"
            mtime = _newest_mtime(entry)
            if mtime is None:
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
                json.dumps(
                    {
                        "event": "sweep_removed",
                        "id": entry.name,
                        "age": age,
                        "kind": kind,
                    }
                ),
                file=sys.stderr,
            )
            removed += 1
    print(json.dumps({"event": "sweep_complete", "removed": removed}), file=sys.stderr)
    return removed


def _skip_orphan_sweep(reason: str) -> int:
    print(
        json.dumps({"event": "orphan_sweep_skipped", "reason": reason}),
        file=sys.stderr,
    )
    return 0


def sweep_orphan_story_dirs(
    story_manager: StoryManager,
    *,
    stories_dir: Path | None = None,
    max_age_seconds: int = MAX_AGE_SECONDS,
    now_seconds: float | None = None,
) -> int:
    """Remove content/stories/<uuid>/ dirs the index no longer references.

    A crash between writing a story's files and updating the index (or between
    dropping the index entry and rmtree'ing the dir) strands the directory: it
    holds real audio but nothing can reach it. Returns the count removed.

    This deletes teacher-uploaded content, so it is deliberately timid. It
    bails out entirely when the index is missing or empty (every dir would look
    orphaned) and when orphans outnumber indexed stories (a restored or corrupt
    index, not ordinary leakage). Survivors are only ever reaped once stale, so
    an in-flight upload is never at risk.
    """
    target_dir = stories_dir if stories_dir is not None else story_manager.CONTENT_DIR
    now = now_seconds if now_seconds is not None else time.time()
    if not target_dir.exists():
        return _skip_orphan_sweep("no_stories_dir")
    if not story_manager.INDEX_FILE.exists():
        return _skip_orphan_sweep("no_index")
    indexed = _indexed_story_ids(story_manager)
    if not indexed:
        return _skip_orphan_sweep("empty_index")

    orphans: list[tuple[Path, float]] = []
    for entry in sorted(target_dir.iterdir()):
        if not entry.is_dir() or entry.name in indexed:
            continue
        mtime = _newest_mtime(entry)
        if mtime is None:
            continue
        orphans.append((entry, now - mtime))

    if len(orphans) > len(indexed):
        return _skip_orphan_sweep("too_many_orphans")

    removed = 0
    for entry, age in orphans:
        if age <= max_age_seconds:
            continue
        try:
            shutil.rmtree(entry)
        except OSError as e:
            print(
                json.dumps(
                    {
                        "event": "orphan_sweep_failed",
                        "id": entry.name,
                        "reason": type(e).__name__,
                    }
                ),
                file=sys.stderr,
            )
            continue
        print(
            json.dumps({"event": "orphan_story_removed", "id": entry.name, "age": age}),
            file=sys.stderr,
        )
        removed += 1
    print(
        json.dumps({"event": "orphan_sweep_complete", "removed": removed}),
        file=sys.stderr,
    )
    return removed
