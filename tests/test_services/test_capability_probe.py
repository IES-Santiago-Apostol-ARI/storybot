"""Unit tests for app.services.capability_probe (CAP-01, CAP-02).

Tests cover all D-05 reason enum branches, env override semantics (D-04),
fail-closed probe-error behavior (D-13), and stderr JSON event shapes.
Uses monkeypatch on thin wrappers (_cuda_is_available, _cuda_device_count,
_get_ram_total) so tests run without torch installed.
"""

import json
import os

import pytest

# This import will FAIL today — RED.
pytest.importorskip(
    "app.services.capability_probe",
    reason="Wave 0 RED stub: implemented in Plan 17-02",
)

from app.services.capability_probe import (  # noqa: E402
    probe_capability,
)

# Module path prefix for monkeypatch.setattr on the thin wrappers.
_MOD = "app.services.capability_probe"


# ---------------------------------------------------------------------------
# Group A — auto-detect path (env unset; monkeypatch thin wrappers)
# ---------------------------------------------------------------------------


class TestProbeAutoDetect:
    def test_cuda_present_and_ram_ok_returns_enabled(self, monkeypatch):
        monkeypatch.delenv("STORYBOT_AI", raising=False)
        monkeypatch.setattr(f"{_MOD}._cuda_is_available", lambda: True)
        monkeypatch.setattr(f"{_MOD}._cuda_device_count", lambda: 1)
        monkeypatch.setattr(f"{_MOD}._get_ram_total", lambda: 8 * 1024**3)
        monkeypatch.setattr(f"{_MOD}._jetson_marker_exists", lambda: False)

        profile = probe_capability()

        assert profile.ai_enabled is True
        assert profile.tts_available is True
        assert profile.cover_gen is True
        assert profile.printer is False
        assert profile.reason == "auto-detect:cuda+ram-ok"

    def test_no_cuda_returns_disabled_no_cuda(self, monkeypatch):
        monkeypatch.delenv("STORYBOT_AI", raising=False)
        monkeypatch.setattr(f"{_MOD}._cuda_is_available", lambda: False)
        monkeypatch.setattr(f"{_MOD}._get_ram_total", lambda: 8 * 1024**3)
        monkeypatch.setattr(f"{_MOD}._jetson_marker_exists", lambda: False)

        profile = probe_capability()

        assert profile.ai_enabled is False
        assert profile.reason == "auto-detect:no-cuda"

    def test_cuda_present_but_low_ram_returns_insufficient_ram(self, monkeypatch):
        monkeypatch.delenv("STORYBOT_AI", raising=False)
        monkeypatch.setattr(f"{_MOD}._cuda_is_available", lambda: True)
        monkeypatch.setattr(f"{_MOD}._cuda_device_count", lambda: 1)
        monkeypatch.setattr(f"{_MOD}._get_ram_total", lambda: 4 * 1024**3)
        monkeypatch.setattr(f"{_MOD}._jetson_marker_exists", lambda: False)

        profile = probe_capability()

        assert profile.ai_enabled is False
        assert profile.reason == "auto-detect:insufficient-ram"

    def test_both_signals_fail_returns_combined_reason(self, monkeypatch):
        monkeypatch.delenv("STORYBOT_AI", raising=False)
        monkeypatch.setattr(f"{_MOD}._cuda_is_available", lambda: False)
        monkeypatch.setattr(f"{_MOD}._get_ram_total", lambda: 4 * 1024**3)
        monkeypatch.setattr(f"{_MOD}._jetson_marker_exists", lambda: False)

        profile = probe_capability()

        assert profile.ai_enabled is False
        assert profile.reason == "auto-detect:no-cuda+insufficient-ram"

    def test_ram_exactly_at_threshold_passes(self, monkeypatch):
        """D-02: threshold is >= 6 GB."""
        monkeypatch.delenv("STORYBOT_AI", raising=False)
        monkeypatch.setattr(f"{_MOD}._cuda_is_available", lambda: True)
        monkeypatch.setattr(f"{_MOD}._cuda_device_count", lambda: 1)
        monkeypatch.setattr(f"{_MOD}._get_ram_total", lambda: 6 * 1024**3)
        monkeypatch.setattr(f"{_MOD}._jetson_marker_exists", lambda: False)

        profile = probe_capability()

        assert profile.ai_enabled is True
        assert profile.reason == "auto-detect:cuda+ram-ok"

    def test_torch_import_missing_treated_as_no_cuda(self, monkeypatch):
        """D-01: default _cuda_is_available returns False when torch missing."""
        monkeypatch.delenv("STORYBOT_AI", raising=False)
        # Do NOT monkeypatch _cuda_is_available — exercise the real function
        # which catches ImportError from missing torch.  On this venv torch is
        # not installed, so it returns False naturally.
        monkeypatch.setattr(f"{_MOD}._get_ram_total", lambda: 8 * 1024**3)
        monkeypatch.setattr(f"{_MOD}._jetson_marker_exists", lambda: False)

        profile = probe_capability()

        assert profile.ai_enabled is False
        assert "no-cuda" in profile.reason


# ---------------------------------------------------------------------------
# Group B — env override path (STORYBOT_AI=0 / 1 / unset / invalid)
# ---------------------------------------------------------------------------


class TestProbeEnvOverride:
    def test_env_var_zero_forces_off_even_when_hardware_capable(self, monkeypatch):
        monkeypatch.setenv("STORYBOT_AI", "0")
        monkeypatch.setattr(f"{_MOD}._cuda_is_available", lambda: True)
        monkeypatch.setattr(f"{_MOD}._cuda_device_count", lambda: 1)
        monkeypatch.setattr(f"{_MOD}._get_ram_total", lambda: 8 * 1024**3)

        profile = probe_capability()

        assert profile.ai_enabled is False
        assert profile.reason == "env-override:forced-off"

    def test_env_var_one_forces_on_even_when_no_cuda(self, monkeypatch):
        monkeypatch.setenv("STORYBOT_AI", "1")
        monkeypatch.setattr(f"{_MOD}._cuda_is_available", lambda: False)
        monkeypatch.setattr(f"{_MOD}._get_ram_total", lambda: 4 * 1024**3)

        profile = probe_capability()

        assert profile.ai_enabled is True
        assert profile.reason == "env-override:forced-on"

    def test_env_var_unset_triggers_auto_detect(self, monkeypatch):
        """Unset env is distinct from '0' — should run auto-detect."""
        monkeypatch.delenv("STORYBOT_AI", raising=False)
        monkeypatch.setattr(f"{_MOD}._cuda_is_available", lambda: True)
        monkeypatch.setattr(f"{_MOD}._cuda_device_count", lambda: 1)
        monkeypatch.setattr(f"{_MOD}._get_ram_total", lambda: 8 * 1024**3)

        profile = probe_capability()

        assert profile.reason == "auto-detect:cuda+ram-ok"

    def test_env_var_invalid_string_is_ignored_falls_back_to_autodetect(
        self, monkeypatch
    ):
        """D-04: only literal '0' and '1' override; anything else -> auto-detect."""
        monkeypatch.setenv("STORYBOT_AI", "yes")
        monkeypatch.setattr(f"{_MOD}._cuda_is_available", lambda: True)
        monkeypatch.setattr(f"{_MOD}._cuda_device_count", lambda: 1)
        monkeypatch.setattr(f"{_MOD}._get_ram_total", lambda: 8 * 1024**3)

        profile = probe_capability()

        assert profile.ai_enabled is True
        assert profile.reason == "auto-detect:cuda+ram-ok"


# ---------------------------------------------------------------------------
# Group C — probe error / fail-closed per D-13
# ---------------------------------------------------------------------------


class TestProbeError:
    def test_torch_raises_runtime_error_returns_probe_error(self, monkeypatch):
        monkeypatch.delenv("STORYBOT_AI", raising=False)

        def _raise():
            raise RuntimeError("CUDA driver mismatch")

        monkeypatch.setattr(f"{_MOD}._cuda_is_available", _raise)

        profile = probe_capability()

        assert profile.ai_enabled is False
        assert profile.reason == "probe-error:RuntimeError"

    def test_psutil_raises_oserror_returns_probe_error(self, monkeypatch):
        monkeypatch.delenv("STORYBOT_AI", raising=False)
        monkeypatch.setattr(f"{_MOD}._cuda_is_available", lambda: True)
        monkeypatch.setattr(f"{_MOD}._cuda_device_count", lambda: 1)

        def _raise():
            raise OSError("no /proc")

        monkeypatch.setattr(f"{_MOD}._get_ram_total", _raise)

        profile = probe_capability()

        assert profile.ai_enabled is False
        assert profile.reason == "probe-error:OSError"

    def test_probe_error_profile_has_all_fields_false(self, monkeypatch):
        monkeypatch.delenv("STORYBOT_AI", raising=False)

        def _raise():
            raise RuntimeError("boom")

        monkeypatch.setattr(f"{_MOD}._cuda_is_available", _raise)

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
        monkeypatch.setattr(f"{_MOD}._cuda_is_available", lambda: True)
        monkeypatch.setattr(f"{_MOD}._cuda_device_count", lambda: 1)
        monkeypatch.setattr(f"{_MOD}._get_ram_total", lambda: 8 * 1024**3)

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

        def _raise():
            raise RuntimeError("CUDA driver mismatch")

        monkeypatch.setattr(f"{_MOD}._cuda_is_available", _raise)

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
        monkeypatch.setattr(f"{_MOD}._cuda_is_available", lambda: False)
        monkeypatch.setattr(f"{_MOD}._get_ram_total", lambda: 4 * 1024**3)

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


# ---------------------------------------------------------------------------
# Group E — .env file loading (load_dotenv called before env var read)
# ---------------------------------------------------------------------------


class TestDotenvLoading:
    def test_load_dotenv_called_before_env_read(self, monkeypatch, tmp_path):
        """probe_capability must call load_dotenv() so .env file is honoured."""
        env_file = tmp_path / ".env"
        env_file.write_text("STORYBOT_AI=1\n")

        # Ensure STORYBOT_AI is NOT in os.environ (simulating fresh process)
        monkeypatch.delenv("STORYBOT_AI", raising=False)

        # Patch the module-level reference to load_dotenv in capability_probe.
        called = []

        def _fake_load_dotenv(**kwargs):
            called.append(True)
            # Simulate what load_dotenv would do
            os.environ["STORYBOT_AI"] = "1"

        monkeypatch.setattr(f"{_MOD}.load_dotenv", _fake_load_dotenv)
        monkeypatch.setattr(f"{_MOD}._cuda_is_available", lambda: False)
        monkeypatch.setattr(f"{_MOD}._get_ram_total", lambda: 4 * 1024**3)

        profile = probe_capability()

        assert called, "load_dotenv was never called"
        assert profile.ai_enabled is True
        assert profile.reason == "env-override:forced-on"


# ---------------------------------------------------------------------------
# Group F — Jetson hardware detection (torch not installed)
# ---------------------------------------------------------------------------


class TestJetsonDetection:
    def test_jetson_detected_via_nv_tegra_release(self, monkeypatch):
        """Jetson with /etc/nv_tegra_release + 8GB RAM should enable AI
        even when torch is not installed (CUDA via apt, not pip)."""
        monkeypatch.delenv("STORYBOT_AI", raising=False)
        monkeypatch.setattr(f"{_MOD}._cuda_is_available", lambda: False)
        monkeypatch.setattr(f"{_MOD}._cuda_device_count", lambda: 0)
        monkeypatch.setattr(f"{_MOD}._get_ram_total", lambda: 8 * 1024**3)

        def _is_file(path):
            return str(path) == "/etc/nv_tegra_release"

        monkeypatch.setattr(f"{_MOD}._jetson_marker_exists", lambda: True)

        profile = probe_capability()

        assert profile.ai_enabled is True
        assert "jetson" in profile.reason

    def test_jetson_with_insufficient_ram_still_disabled(self, monkeypatch):
        """Jetson with <6GB RAM should NOT enable AI."""
        monkeypatch.delenv("STORYBOT_AI", raising=False)
        monkeypatch.setattr(f"{_MOD}._cuda_is_available", lambda: False)
        monkeypatch.setattr(f"{_MOD}._cuda_device_count", lambda: 0)
        monkeypatch.setattr(f"{_MOD}._get_ram_total", lambda: 4 * 1024**3)
        monkeypatch.setattr(f"{_MOD}._jetson_marker_exists", lambda: True)

        profile = probe_capability()

        assert profile.ai_enabled is False

    def test_non_jetson_without_cuda_stays_disabled(self, monkeypatch):
        """Non-Jetson without torch CUDA stays disabled."""
        monkeypatch.delenv("STORYBOT_AI", raising=False)
        monkeypatch.setattr(f"{_MOD}._cuda_is_available", lambda: False)
        monkeypatch.setattr(f"{_MOD}._get_ram_total", lambda: 8 * 1024**3)
        monkeypatch.setattr(f"{_MOD}._jetson_marker_exists", lambda: False)

        profile = probe_capability()

        assert profile.ai_enabled is False
        assert "no-cuda" in profile.reason
