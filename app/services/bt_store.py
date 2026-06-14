"""Single-speaker Bluetooth persistence over content/bt_devices.json.

Mirrors ConfigManager (default path, load-with-defaults) but upgrades the
write to an atomic tmp + os.replace per CONTEXT D-03. Persists exactly ONE
last_speaker (D-01, N=1) — not a list.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path


class BtDeviceStore:
    """Persist the last-connected Bluetooth speaker to a JSON file.

    Shape: ``{"last_speaker": {"name", "mac", "last_connected"}}`` (D-02/D-03).
    Missing or corrupt file yields ``None`` (never raises) — threat T-26-03.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        """Initialize the store.

        Args:
            path: Path to the JSON file. Defaults to
                ``<project_root>/content/bt_devices.json`` (mirrors ConfigManager).
        """
        if path is None:
            # bt_store.py lives at app/services/bt_store.py; two parents up is
            # the project root (mirrors ConfigManager's app/config.py default
            # path, which is one parent up). CONTEXT D-02: content/bt_devices.json
            # at the project root.
            project_root = Path(__file__).parent.parent.parent
            path = project_root / "content" / "bt_devices.json"
        self.path = Path(path)

    def get_last_speaker(self) -> dict | None:
        """Return the last speaker dict, or ``None`` if missing/corrupt.

        Never raises: a missing file or non-JSON/invalid JSON resolves to
        ``None`` (D-03, threat T-26-03).
        """
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text())
            return data.get("last_speaker")
        except (json.JSONDecodeError, TypeError, AttributeError):
            return None

    def save_last_speaker(self, name: str, mac: str) -> None:
        """Persist exactly one last speaker, atomically (D-01/D-02/D-03).

        Writes a sibling ``.json.tmp`` file then ``os.replace``s it into
        place so a crash mid-write never leaves a truncated file.

        Args:
            name: Speaker display name.
            mac: Speaker MAC address.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "last_speaker": {
                "name": name,
                "mac": mac,
                "last_connected": datetime.now(timezone.utc).isoformat(),
            }
        }
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, self.path)
