"""Phase 21 install script source-assertion tests (DEP-01)."""
from pathlib import Path
import re
import pytest

INSTALL_SCRIPT = Path("deploy/install.sh")
SERVICE_FILE = Path("deploy/storybot.service")


@pytest.fixture(scope="module")
def script_text():
    """Read install.sh once per module."""
    return INSTALL_SCRIPT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def service_text():
    """Read storybot.service once per module."""
    return SERVICE_FILE.read_text(encoding="utf-8")


class TestInstallFlags:
    """Source-assertion tests for --ai/--no-ai CLI flags (DEP-01, D-01)."""

    def test_ai_flag_case_exists(self, script_text):
        """Script contains '--ai)' case in the argument parser."""
        assert "--ai)" in script_text, (
            "Missing --ai) case in argument parser case block"
        )

    def test_no_ai_flag_case_exists(self, script_text):
        """Script contains '--no-ai)' case in the argument parser."""
        assert "--no-ai)" in script_text, (
            "Missing --no-ai) case in argument parser case block"
        )

    def test_ai_flag_variable_declared(self, script_text):
        """Script declares AI_FLAG variable initialized to empty string."""
        assert re.search(r'AI_FLAG\s*=\s*""', script_text) or re.search(
            r"AI_FLAG\s*=\s*''", script_text
        ), "Missing AI_FLAG variable initialization"


class TestAutoDetect:
    """Source-assertion tests for GPU auto-detection (DEP-01, D-02)."""

    def test_nvidia_smi_probe_exists(self, script_text):
        """Script contains nvidia-smi for GPU detection."""
        assert "nvidia-smi" in script_text, (
            "Missing nvidia-smi GPU detection probe"
        )

    def test_dev_nvidia_fallback_exists(self, script_text):
        """Script contains /dev/nvidia fallback detection."""
        assert "/dev/nvidia" in script_text, (
            "Missing /dev/nvidia* fallback detection"
        )

    def test_ai_mode_variable_set(self, script_text):
        """Script contains AI_MODE=true and AI_MODE=false assignments."""
        assert "AI_MODE=true" in script_text, "Missing AI_MODE=true assignment"
        assert "AI_MODE=false" in script_text, "Missing AI_MODE=false assignment"


class TestEnvFileWrite:
    """Source-assertion tests for .env file writing (DEP-01, D-04)."""

    def test_env_file_write_ai_enabled(self, script_text):
        """Script writes STORYBOT_AI=1 to .env."""
        assert "STORYBOT_AI=1" in script_text, (
            "Missing STORYBOT_AI=1 write to .env"
        )

    def test_env_file_write_ai_disabled(self, script_text):
        """Script writes STORYBOT_AI=0 to .env."""
        assert "STORYBOT_AI=0" in script_text, (
            "Missing STORYBOT_AI=0 write to .env"
        )

    def test_env_file_chown(self, script_text):
        """Script chowns .env file to INSTALL_USER."""
        assert re.search(r"chown.*\.env", script_text) or re.search(
            r"chown.*INSTALL_USER", script_text
        ), "Missing chown of .env to INSTALL_USER"


class TestServiceFile:
    """Source-assertion tests for storybot.service (DEP-01, D-05, D-06)."""

    def test_environment_file_directive_exists(self, service_text):
        """service file contains EnvironmentFile=-/home/ari/storybot/.env."""
        assert "EnvironmentFile=-/home/ari/storybot/.env" in service_text, (
            "Missing EnvironmentFile=-/home/ari/storybot/.env directive"
        )

    def test_environment_file_has_dash_prefix(self, service_text):
        """EnvironmentFile uses the optional dash prefix for missing-file tolerance."""
        match = re.search(r"EnvironmentFile=-", service_text)
        assert match, (
            "EnvironmentFile directive missing dash (-) prefix for optional file"
        )


class TestDetectionOrder:
    """Source-assertion tests for detection ordering (DEP-01)."""

    def test_detection_before_step_1(self, script_text):
        """AI_MODE detection block appears before 'Step 1:' in the script."""
        ai_mode_pos = script_text.find("AI_MODE=true")
        step1_pos = script_text.find("Step 1:")
        assert ai_mode_pos > 0, "AI_MODE=true not found in script"
        assert step1_pos > 0, "Step 1: not found in script"
        assert ai_mode_pos < step1_pos, (
            f"AI_MODE detection at pos {ai_mode_pos} must come before "
            f"Step 1: at pos {step1_pos}"
        )

    def test_env_write_after_detection(self, script_text):
        """STORYBOT_AI= write appears after AI_MODE assignment."""
        ai_mode_pos = script_text.find("AI_MODE=")
        env_write_pos = script_text.find("STORYBOT_AI=")
        assert ai_mode_pos > 0, "AI_MODE assignment not found"
        assert env_write_pos > 0, "STORYBOT_AI= write not found"
        assert env_write_pos > ai_mode_pos, (
            f"STORYBOT_AI= write at pos {env_write_pos} must come after "
            f"AI_MODE= at pos {ai_mode_pos}"
        )

    def test_ai_mode_in_header_banner(self, script_text):
        """AI mode display appears in the header banner section."""
        banner_pos = script_text.find("StoryBot Installation Script")
        ai_display_pos = script_text.find("AI mode:")
        assert banner_pos > 0, "Header banner not found"
        assert ai_display_pos > 0, "AI mode display not found in header banner"
        assert ai_display_pos > banner_pos, (
            "AI mode display must appear after installation script header"
        )


# ---------------------------------------------------------------------------
# Phase 21 Plan 02: AI-conditional step wrapping, arch gate removal, banner
# (DEP-02, DEP-03)
# ---------------------------------------------------------------------------


def _find_ai_block(text, start_from=0):
    """Return (start, end) of the next ``if [[ "$AI_MODE" == true ]]`` block.

    end is the position just past the matching ``fi``.  Returns (-1, -1) if
    not found.
    """
    idx = text.find('if [[ "$AI_MODE" == true ]]', start_from)
    if idx == -1:
        return -1, -1
    # Walk forward counting if/fi to find the matching fi
    depth = 0
    i = idx
    while i < len(text):
        line_start = text.rfind("\n", 0, i) + 1
        rest_of_line = text[i:].split("\n", 1)[0].strip()
        if rest_of_line.startswith("if ") or rest_of_line == "if":
            depth += 1
        elif rest_of_line == "fi":
            depth -= 1
            if depth == 0:
                return idx, i + 2  # include "fi"
        i = text.find("\n", i) + 1
        if i == 0:
            break
    return -1, -1


def _is_inside_ai_block(text, target):
    """Return True if *target* string falls inside any AI_MODE == true block."""
    search_from = 0
    while True:
        start, end = _find_ai_block(text, search_from)
        if start == -1:
            return False
        pos = text.find(target, start)
        if start <= pos < end:
            return True
        search_from = end


class TestArchGate:
    """DEP-03, D-03: aarch64-only gate is removed from install.sh."""

    def test_aarch64_exit_removed(self, script_text):
        """Script no longer contains the old exit-on-non-aarch64 message."""
        assert "This script is for Jetson (aarch64) only" not in script_text, (
            "Old aarch64-only exit message still present -- should be removed"
        )

    def test_no_architecture_restriction(self, script_text):
        """Script no longer uses uname -m for architecture gating."""
        assert not re.search(r"uname\s+-m.*exit", script_text, re.DOTALL), (
            "uname -m is still used for architecture gating/exit -- should be removed"
        )


class TestAIConditionals:
    """DEP-02, D-07: AI-specific steps wrapped in AI_MODE conditionals."""

    def test_nvidia_jetpack_in_ai_block(self, script_text):
        """nvidia-jetpack apt install is inside an AI_MODE == true block."""
        assert _is_inside_ai_block(script_text, "nvidia-jetpack"), (
            "nvidia-jetpack must appear inside an AI_MODE == true conditional, "
            "not in the common apt-get line"
        )

    def test_sudoers_in_ai_block(self, script_text):
        """sudoers.d/storybot-llama is inside an AI_MODE == true block."""
        assert _is_inside_ai_block(
            script_text, "sudoers.d/storybot-llama"
        ), (
            "sudoers entry for llama-server must be inside an AI_MODE == true block"
        )

    def test_model_download_gated_by_ai(self, script_text):
        """Step 3 model download is gated by AI_MODE (not just DEV_MODE)."""
        assert _is_inside_ai_block(
            script_text, "download-models.sh"
        ), (
            "TTS model download (download-models.sh) must be inside "
            "an AI_MODE == true conditional block"
        )


class TestKioskConditionals:
    """DEP-03, D-08: kiosk display steps wrapped in AI_MODE conditionals."""

    def test_gdm_autologin_in_ai_block(self, script_text):
        """gdm3/custom.conf reference is inside an AI_MODE == true block."""
        assert _is_inside_ai_block(script_text, "gdm3/custom.conf"), (
            "GDM3 autologin (Step 8) must be inside an AI_MODE == true block"
        )

    def test_firefox_kiosk_in_ai_block(self, script_text):
        """storybot-kiosk.desktop is inside an AI_MODE == true block."""
        assert _is_inside_ai_block(
            script_text, "storybot-kiosk.desktop"
        ), (
            "Firefox kiosk autostart (Step 9) must be inside an "
            "AI_MODE == true block"
        )

    def test_screen_settings_in_ai_block(self, script_text):
        """storybot-screen-setup.desktop is inside an AI_MODE == true block."""
        assert _is_inside_ai_block(
            script_text, "storybot-screen-setup.desktop"
        ), (
            "Screen-never-blanks (Step 10) must be inside an "
            "AI_MODE == true block"
        )


class TestCommonSteps:
    """DEP-03, D-09 (with D-08 precedence): common steps NOT in AI blocks."""

    def test_nginx_not_in_ai_block(self, script_text):
        """nginx is NOT inside an AI_MODE conditional (common package)."""
        assert not _is_inside_ai_block(script_text, "nginx"), (
            "nginx should NOT be inside an AI_MODE block -- "
            "it is a common package for all devices"
        )

    def test_storybot_service_not_in_ai_block(self, script_text):
        """cp storybot.service is NOT inside an AI_MODE conditional."""
        assert not _is_inside_ai_block(
            script_text, "storybot.service"
        ), (
            "storybot.service install should NOT be inside an AI_MODE block -- "
            "it is a common step for all devices"
        )

    def test_uv_sync_not_in_ai_block(self, script_text):
        """uv sync is NOT inside an AI_MODE conditional."""
        assert not _is_inside_ai_block(script_text, "uv sync"), (
            "uv sync should NOT be inside an AI_MODE block -- "
            "it is a common step for all devices"
        )


class TestCompletionBanner:
    """D-11: completion banner shows AI vs stories-only mode."""

    def test_banner_has_ai_mode_branch(self, script_text):
        """Banner has conditional text for AI mode."""
        banner_pos = script_text.find("Installation Complete")
        assert banner_pos > 0, "Installation Complete banner not found"
        after_banner = script_text[banner_pos:]
        assert re.search(
            r"AI\s*Mode|Full\s*AI|AI\s*enabled", after_banner, re.IGNORECASE
        ), (
            "Completion banner must show AI mode indicator "
            "(e.g., 'Full AI Mode' or 'AI Mode')"
        )

    def test_banner_has_stories_only_branch(self, script_text):
        """Banner has text for stories-only mode."""
        banner_pos = script_text.find("Installation Complete")
        assert banner_pos > 0, "Installation Complete banner not found"
        after_banner = script_text[banner_pos:]
        assert re.search(
            r"stories.only|Stories\s*Only|B.asico|modo\s*b..sico",
            after_banner,
            re.IGNORECASE,
        ), (
            "Completion banner must show stories-only mode indicator "
            "(e.g., 'Stories-Only Mode')"
        )

    def test_banner_lists_skipped_items(self, script_text):
        """Banner mentions skipped items for non-AI mode."""
        banner_pos = script_text.find("Installation Complete")
        assert banner_pos > 0, "Installation Complete banner not found"
        after_banner = script_text[banner_pos:]
        assert re.search(r"[Ss]kipped", after_banner), (
            "Completion banner should list skipped items for stories-only mode"
        )
