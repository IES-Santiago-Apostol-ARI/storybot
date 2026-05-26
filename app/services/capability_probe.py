"""CAP-01, CAP-02: Startup capability probe for v1.3 device self-awareness.

Pure-function module — no FastAPI imports, no app.state mutation.
Honors STORYBOT_AI env var blindly (D-04), then probes CUDA via torch
(D-01) and RAM via psutil (D-02).  Broad try/except returns fail-closed
profile on any error (D-13).  All events emitted as single-line JSON to
stderr.
"""

from __future__ import annotations

import json
import os
import sys

import psutil

from app.models.capability import CapabilityProfile

RAM_THRESHOLD_GB: int = 6  # CONTEXT.md D-02
ENV_VAR: str = "STORYBOT_AI"  # CONTEXT.md D-04


def probe_capability() -> CapabilityProfile:
    """Detect AI capability and return a CapabilityProfile.

    Env var STORYBOT_AI overrides hardware detection (D-04):
      - "1" → force-enabled, "0" → force-disabled, else auto-detect.
    """
    try:
        env_val = os.environ.get(ENV_VAR)

        # --- Env override: forced-on (D-04) ---
        if env_val == "1":
            # Probe hardware to check for contradiction warning (D-04).
            cuda_present, ram_ok, gpu_name, ram_gb = _probe_hardware()
            profile = CapabilityProfile(
                ai_enabled=True,
                tts_available=True,
                cover_gen=True,
                printer=False,
                reason="env-override:forced-on",
            )
            # D-04 contradiction warning when hardware would not pass auto-detect.
            if not (cuda_present and ram_ok):
                print(
                    json.dumps(
                        {
                            "event": "capability_env_contradiction",
                            "env": "1",
                            "cuda_present": cuda_present,
                            "ram_ok": ram_ok,
                        }
                    ),
                    file=sys.stderr,
                )
            print(
                json.dumps(
                    {
                        "event": "capability_probe",
                        "result": "env-override:forced-on",
                        "reason": profile.reason,
                        "gpu": gpu_name,
                        "ram_gb": ram_gb,
                    }
                ),
                file=sys.stderr,
            )
            return profile

        # --- Env override: forced-off (D-04) ---
        if env_val == "0":
            profile = CapabilityProfile(
                ai_enabled=False,
                tts_available=False,
                cover_gen=False,
                printer=False,
                reason="env-override:forced-off",
            )
            print(
                json.dumps(
                    {
                        "event": "capability_probe",
                        "result": "env-override:forced-off",
                        "reason": profile.reason,
                        "gpu": None,
                        "ram_gb": None,
                    }
                ),
                file=sys.stderr,
            )
            return profile

        # --- Auto-detect (env unset or non-"0"/"1" string) ---
        cuda_present, ram_ok, gpu_name, ram_gb = _probe_hardware()

        reason = _compose_autodetect_reason(cuda_present, ram_ok)
        ai_enabled = cuda_present and ram_ok

        profile = CapabilityProfile(
            ai_enabled=ai_enabled,
            tts_available=ai_enabled,
            cover_gen=ai_enabled,
            printer=False,
            reason=reason,
        )
        print(
            json.dumps(
                {
                    "event": "capability_probe",
                    "result": reason,
                    "reason": reason,
                    "gpu": gpu_name,
                    "ram_gb": ram_gb,
                }
            ),
            file=sys.stderr,
        )
        return profile

    except Exception as e:
        # D-13: broad fail-closed — never crash startup.
        print(
            json.dumps(
                {
                    "event": "capability_probe_failed",
                    "reason": type(e).__name__,
                    "message": str(e),
                }
            ),
            file=sys.stderr,
        )
        return CapabilityProfile(
            ai_enabled=False,
            tts_available=False,
            cover_gen=False,
            printer=False,
            reason=f"probe-error:{type(e).__name__}",
        )


def _cuda_is_available() -> bool:
    """Thin wrapper — monkeypatchable when torch is not installed."""
    try:
        import torch

        return bool(torch.cuda.is_available())
    except ImportError:
        return False


def _cuda_device_count() -> int:
    """Thin wrapper — monkeypatchable when torch is not installed."""
    try:
        import torch

        return torch.cuda.device_count()
    except ImportError:
        return 0


def _cuda_get_device_name(index: int = 0) -> str | None:
    """Thin wrapper — monkeypatchable when torch is not installed."""
    try:
        import torch

        return torch.cuda.get_device_name(index)
    except Exception:
        return None


def _get_ram_total() -> int:
    """Thin wrapper around psutil.virtual_memory().total — monkeypatchable."""
    return psutil.virtual_memory().total


def _probe_hardware() -> tuple[bool, bool, str | None, float | None]:
    """Return (cuda_present, ram_ok, gpu_name, ram_gb).

    torch import is deferred to the function body so the module imports
    cleanly on a non-AI device without jetson extras (D-01).
    """
    cuda_present = _cuda_is_available() and _cuda_device_count() > 0

    gpu_name: str | None = None
    if cuda_present:
        gpu_name = _cuda_get_device_name(0)

    total = _get_ram_total()
    ram_gb = round(total / (1024**3), 1)
    ram_ok = total >= RAM_THRESHOLD_GB * 1024**3

    return cuda_present, ram_ok, gpu_name, ram_gb


def _compose_autodetect_reason(cuda_present: bool, ram_ok: bool) -> str:
    """Map the two boolean signals to a D-05 reason slug."""
    if cuda_present and ram_ok:
        return "auto-detect:cuda+ram-ok"
    if not cuda_present and not ram_ok:
        return "auto-detect:no-cuda+insufficient-ram"
    if not cuda_present:
        return "auto-detect:no-cuda"
    return "auto-detect:insufficient-ram"
