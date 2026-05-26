"""Wave 0 RED stubs for app.services.capability_probe (CAP-01, CAP-02).

These tests fail today because app.services.capability_probe does not exist.
Plan 17-02 makes them GREEN.
"""

import json
import sys
from types import SimpleNamespace

import pytest

# This import will FAIL today — RED.
pytest.importorskip(
    "app.services.capability_probe",
    reason="Wave 0 RED stub: implemented in Plan 17-02",
)

from app.services.capability_probe import (  # noqa: E402
    probe_capability,
    RAM_THRESHOLD_GB,
    ENV_VAR,
)
from app.models.capability import CapabilityProfile  # noqa: E402


# ---------------------------------------------------------------------------
# Group A — auto-detect path (env unset; monkeypatch torch + psutil)
# ---------------------------------------------------------------------------


class TestProbeAutoDetect:
    def test_cuda_present_and_ram_ok_returns_enabled(self, monkeypatch):
        monkeypatch.delenv("STORYBOT_AI", raising=False)
        monkeypatch.setattr("torch.cuda.is_available", lambda: True)
        monkeypatch.setattr("torch.cuda.device_count", lambda: 1)
        monkeypatch.setattr(
            "psutil.virtual_memory",
            lambda: SimpleNamespace(total=8 * 1024**3),
        )

        profile = probe_capability()

        assert profile.ai_enabled is True
        assert profile.tts_available is True
        assert profile.cover_gen is True
        assert profile.printer is False
        assert profile.reason == "auto-detect:cuda+ram-ok"

    def test_no_cuda_returns_disabled_no_cuda(self, monkeypatch):
        monkeypatch.delenv("STORYBOT_AI", raising=False)
        monkeypatch.setattr("torch.cuda.is_available", lambda: False)
        monkeypatch.setattr(
            "psutil.virtual_memory",
            lambda: SimpleNamespace(total=8 * 1024**3),
        )

        profile = probe_capability()

        assert profile.ai_enabled is False
        assert profile.reason == "auto-detect:no-cuda"

    def test_cuda_present_but_low_ram_returns_insufficient_ram(self, monkeypatch):
        monkeypatch.delenv("STORYBOT_AI", raising=False)
        monkeypatch.setattr("torch.cuda.is_available", lambda: True)
        monkeypatch.setattr("torch.cuda.device_count", lambda: 1)
        monkeypatch.setattr(
            "psutil.virtual_memory",
            lambda: SimpleNamespace(total=4 * 1024**3),
        )

        profile = probe_capability()

        assert profile.ai_enabled is False
        assert profile.reason == "auto-detect:insufficient-ram"

    def test_both_signals_fail_returns_combined_reason(self, monkeypatch):
        monkeypatch.delenv("STORYBOT_AI", raising=False)
        monkeypatch.setattr("torch.cuda.is_available", lambda: False)
        monkeypatch.setattr(
            "psutil.virtual_memory",
            lambda: SimpleNamespace(total=4 * 1024**3),
        )

        profile = probe_capability()

        assert profile.ai_enabled is False
        assert profile.reason == "auto-detect:no-cuda+insufficient-ram"

    def test_ram_exactly_at_threshold_passes(self, monkeypatch):
        """D-02: threshold is >= 6 GB."""
        monkeypatch.delenv("STORYBOT_AI", raising=False)
        monkeypatch.setattr("torch.cuda.is_available", lambda: True)
        monkeypatch.setattr("torch.cuda.device_count", lambda: 1)
        monkeypatch.setattr(
            "psutil.virtual_memory",
            lambda: SimpleNamespace(total=6 * 1024**3),
        )

        profile = probe_capability()

        assert profile.ai_enabled is True
        assert profile.reason == "auto-detect:cuda+ram-ok"

    def test_torch_import_missing_treated_as_no_cuda(self, monkeypatch):
        """D-01: ImportError from missing torch treated as no CUDA."""
        monkeypatch.delenv("STORYBOT_AI", raising=False)
        monkeypatch.setitem(sys.modules, "torch", None)
        monkeypatch.setattr(
            "psutil.virtual_memory",
            lambda: SimpleNamespace(total=8 * 1024**3),
        )

        profile = probe_capability()

        assert profile.ai_enabled is False
        assert "no-cuda" in profile.reason


# ---------------------------------------------------------------------------
# Group B — env override path (STORYBOT_AI=0 / 1 / unset / invalid)
# ---------------------------------------------------------------------------


class TestProbeEnvOverride:
    def test_env_var_zero_forces_off_even_when_hardware_capable(self, monkeypatch):
        monkeypatch.setenv("STORYBOT_AI", "0")
        monkeypatch.setattr("torch.cuda.is_available", lambda: True)
        monkeypatch.setattr(
            "psutil.virtual_memory",
            lambda: SimpleNamespace(total=8 * 1024**3),
        )

        profile = probe_capability()

        assert profile.ai_enabled is False
        assert profile.reason == "env-override:forced-off"

    def test_env_var_one_forces_on_even_when_no_cuda(self, monkeypatch):
        monkeypatch.setenv("STORYBOT_AI", "1")
        monkeypatch.setattr("torch.cuda.is_available", lambda: False)
        monkeypatch.setattr(
            "psutil.virtual_memory",
            lambda: SimpleNamespace(total=4 * 1024**3),
        )

        profile = probe_capability()

        assert profile.ai_enabled is True
        assert profile.reason == "env-override:forced-on"

    def test_env_var_unset_triggers_auto_detect(self, monkeypatch):
        """Unset env is distinct from '0' — should run auto-detect."""
        monkeypatch.delenv("STORYBOT_AI", raising=False)
        monkeypatch.setattr("torch.cuda.is_available", lambda: True)
        monkeypatch.setattr("torch.cuda.device_count", lambda: 1)
        monkeypatch.setattr(
            "psutil.virtual_memory",
            lambda: SimpleNamespace(total=8 * 1024**3),
        )

        profile = probe_capability()

        assert profile.reason == "auto-detect:cuda+ram-ok"

    def test_env_var_invalid_string_is_ignored_falls_back_to_autodetect(
        self, monkeypatch
    ):
        """D-04: only literal '0' and '1' override; anything else → auto-detect."""
        monkeypatch.setenv("STORYBOT_AI", "yes")
        monkeypatch.setattr("torch.cuda.is_available", lambda: True)
        monkeypatch.setattr("torch.cuda.device_count", lambda: 1)
        monkeypatch.setattr(
            "psutil.virtual_memory",
            lambda: SimpleNamespace(total=8 * 1024**3),
        )

        profile = probe_capability()

        assert profile.ai_enabled is True
        assert profile.reason == "auto-detect:cuda+ram-ok"


# ---------------------------------------------------------------------------
# Group C — probe error / fail-closed per D-13
# ---------------------------------------------------------------------------


class TestProbeError:
    def test_torch_raises_runtime_error_returns_probe_error(self, monkeypatch):
        monkeypatch.delenv("STORYBOT_AI", raising=False)
        monkeypatch.setattr(
            "torch.cuda.is_available",
            lambda: (_ for _ in ()).throw(RuntimeError("CUDA driver mismatch")),
        )

        profile = probe_capability()

        assert profile.ai_enabled is False
        assert profile.reason == "probe-error:RuntimeError"

    def test_psutil_raises_oserror_returns_probe_error(self, monkeypatch):
        monkeypatch.delenv("STORYBOT_AI", raising=False)
        monkeypatch.setattr("torch.cuda.is_available", lambda: True)
        monkeypatch.setattr("torch.cuda.device_count", lambda: 1)
        monkeypatch.setattr(
            "psutil.virtual_memory",
            lambda: (_ for _ in ()).throw(OSError("no /proc")),
        )

        profile = probe_capability()

        assert profile.ai_enabled is False
        assert profile.reason == "probe-error:OSError"

    def test_probe_error_profile_has_all_fields_false(self, monkeypatch):
        monkeypatch.delenv("STORYBOT_AI", raising=False)
        monkeypatch.setattr(
            "torch.cuda.is_available",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        profile = probe_capability()

        assert profile.ai_enabled is False
        assert profile.tts_available is False
        assert profile.cover_gen is False
        assert profile.printer is False


# ---------------------------------------------------------------------------
# Group D — stderr JSON event shapes
# ---------------------------------------------------------------------------


class TestProbeStderrEvents:
    def test_success_path_emits_capability_probe_event(self, monkeypatch, capsys):
        monkeypatch.delenv("STORYBOT_AI", raising=False)
        monkeypatch.setattr("torch.cuda.is_available", lambda: True)
        monkeypatch.setattr("torch.cuda.device_count", lambda: 1)
        monkeypatch.setattr(
            "psutil.virtual_memory",
            lambda: SimpleNamespace(total=8 * 1024**3),
        )

        probe_capability()

        captured = capsys.readouterr()
        events = [
            json.loads(line)
            for line in captured.err.strip().split("\n")
            if line.strip()
        ]
        probe_event = next(e for e in events if e["event"] == "capability_probe")
        assert probe_event["result"] is not None
        assert probe_event["reason"] == "auto-detect:cuda+ram-ok"
        assert "gpu" in probe_event
        assert "ram_gb" in probe_event

    def test_failure_path_emits_capability_probe_failed_event(
        self, monkeypatch, capsys
    ):
        monkeypatch.delenv("STORYBOT_AI", raising=False)
        monkeypatch.setattr(
            "torch.cuda.is_available",
            lambda: (_ for _ in ()).throw(RuntimeError("CUDA driver mismatch")),
        )

        probe_capability()

        captured = capsys.readouterr()
        events = [
            json.loads(line)
            for line in captured.err.strip().split("\n")
            if line.strip()
        ]
        failed_event = next(
            e for e in events if e["event"] == "capability_probe_failed"
        )
        assert failed_event["reason"] == "RuntimeError"
        assert "message" in failed_event

    def test_env_override_contradicting_hardware_logs_warning_to_stderr(
        self, monkeypatch, capsys
    ):
        """D-04: env=1 with no CUDA must log a contradiction warning."""
        monkeypatch.setenv("STORYBOT_AI", "1")
        monkeypatch.setattr("torch.cuda.is_available", lambda: False)
        monkeypatch.setattr(
            "psutil.virtual_memory",
            lambda: SimpleNamespace(total=4 * 1024**3),
        )

        probe_capability()

        captured = capsys.readouterr()
        events = [
            json.loads(line)
            for line in captured.err.strip().split("\n")
            if line.strip()
        ]
        # Must contain a contradiction event or a capability_probe event
        # with a warning key documenting the hardware mismatch (D-04).
        kinds = [e["event"] for e in events]
        assert "capability_env_contradiction" in kinds or any(
            "warning" in e for e in events if e["event"] == "capability_probe"
        ), (
            "Expected capability_env_contradiction event or warning field "
            "in capability_probe event when env=1 but hardware is not capable"
        )
