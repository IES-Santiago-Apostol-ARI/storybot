"""Atomic JSON file writes to prevent corruption on power cuts."""

import json
import os
from pathlib import Path


def write_json_atomic(
    path: Path,
    data: object,
    *,
    indent: int = 2,
    ensure_ascii: bool = True,
) -> None:
    """Write JSON so a power cut leaves either the old file or the new one.

    Strategy: write to a PID-suffixed tmp file in the same directory, fsync
    the tmp file, os.replace() it over the target (atomic on POSIX), then
    fsync the parent directory inode.  On any failure the tmp file is cleaned
    up and the original file is untouched.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")

    fd: int | None = None
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = None  # fdopen takes ownership
            json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii)
            f.flush()
            os.fsync(f.fileno())

        os.replace(str(tmp), str(path))

        dir_fd = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
