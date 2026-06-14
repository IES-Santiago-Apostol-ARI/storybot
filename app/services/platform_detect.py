"""3-way platform detection: jetson | rpi | generic (CONTEXT D-08/D-09).

Reuses capability_probe._jetson_marker_exists rather than duplicating the
/etc/nv_tegra_release literal (PATTERNS constraint). Detection is
informational only this phase (D-07) — no behavior is gated on it.
"""

from pathlib import Path

from app.services.capability_probe import _jetson_marker_exists


def detect_platform() -> str:
    """Return the detected platform: ``"jetson"``, ``"rpi"``, or ``"generic"``.

    Order of checks (D-08):
      1. Jetson marker (/etc/nv_tegra_release) → ``"jetson"``.
      2. /proc/device-tree/model contains "raspberry pi" → ``"rpi"``.
      3. Otherwise → ``"generic"`` (D-09 non-fatal default).

    Never raises: an OSError reading /proc/device-tree/model is swallowed
    and resolves to ``"generic"`` (threat T-26-04).
    """
    if _jetson_marker_exists():
        return "jetson"

    model = Path("/proc/device-tree/model")
    try:
        if (
            model.is_file()
            and "raspberry pi" in model.read_text(errors="ignore").lower()
        ):
            return "rpi"
    except OSError:
        # D-09 / T-26-04: OS marker read failed — non-fatal, fall through.
        pass

    return "generic"
