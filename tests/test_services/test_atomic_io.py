"""Tests for atomic JSON write helper."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest


class TestWriteJsonAtomic:
    """Test write_json_atomic correctness and crash safety."""

    def test_writes_new_content_to_destination(self, tmp_path: Path) -> None:
        """The destination file contains the new JSON after a successful write."""
        from app.services.atomic_io import write_json_atomic

        dest = tmp_path / "data.json"
        dest.write_text(json.dumps({"old": "value"}))

        write_json_atomic(dest, {"new": "value"})

        data = json.loads(dest.read_text())
        assert data == {"new": "value"}

    def test_preserves_old_content_on_replace_failure(self, tmp_path: Path) -> None:
        """If os.replace fails, the old file content is intact and no *.tmp remains."""
        from app.services.atomic_io import write_json_atomic

        dest = tmp_path / "data.json"
        old_content = {"old": "value"}
        dest.write_text(json.dumps(old_content))

        def failing_replace(*args, **kwargs):
            raise OSError("simulated power cut")

        with patch("os.replace", failing_replace):
            with pytest.raises(OSError):
                write_json_atomic(dest, {"new": "value"})

        assert json.loads(dest.read_text()) == old_content
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0, f"Orphan tmp files left: {tmp_files}"

    def test_fsync_called_before_replace(self, tmp_path: Path) -> None:
        """os.fsync on the tmp file happens before os.replace."""
        from app.services.atomic_io import write_json_atomic

        dest = tmp_path / "data.json"
        call_order: list[str] = []

        original_fsync = os.fsync
        original_replace = os.replace

        def tracked_fsync(fd: int) -> None:
            call_order.append("fsync")
            original_fsync(fd)

        def tracked_replace(src, dst) -> None:
            call_order.append("replace")
            original_replace(src, dst)

        with patch("os.fsync", tracked_fsync):
            with patch("os.replace", tracked_replace):
                write_json_atomic(dest, {"test": True})

        fsync_idx = call_order.index("fsync")
        replace_idx = call_order.index("replace")
        assert (
            fsync_idx < replace_idx
        ), f"fsync must precede replace; got order: {call_order}"

    def test_unicode_round_trip_with_ensure_ascii_false(self, tmp_path: Path) -> None:
        """Unicode characters survive a round-trip with ensure_ascii=False."""
        from app.services.atomic_io import write_json_atomic

        dest = tmp_path / "data.json"
        data = {"title": "El robot 🤖 y la luna 🌙", "emoji": "📚"}

        write_json_atomic(dest, data, ensure_ascii=False)

        loaded = json.loads(dest.read_text(encoding="utf-8"))
        assert loaded == data
