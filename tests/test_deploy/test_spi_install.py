import pathlib

def _script_text():
    """Read deploy/install.sh for source assertion."""
    return pathlib.Path("deploy/install.sh").read_text()


def test_udev_rule_content_present():
    """The udev rule for spidev uses GROUP='spi' and MODE='0660' (not 0666/plugdev)."""
    txt = _script_text()
    assert 'SUBSYSTEM=="spidev"' in txt, "Missing spidev udev subsystem match"
    assert 'GROUP="spi"' in txt, "Missing GROUP=spi in udev rule"
    assert 'MODE="0660"' in txt, "Missing MODE=0660 in udev rule (least-privilege)"


def test_udev_rule_file_path():
    """The udev rule is written to /etc/udev/rules.d/99-storybot-spi.rules."""
    txt = _script_text()
    assert "/etc/udev/rules.d/99-storybot-spi.rules" in txt, (
        "Missing 99-storybot-spi.rules file path in install.sh"
    )


def test_groupadd_spi_present():
    """groupadd -f spi is present for the dedicated least-privilege group."""
    txt = _script_text()
    assert "groupadd -f spi" in txt, "Missing 'groupadd -f spi' in install.sh"


def test_usermod_spi_present():
    """usermod -aG spi $INSTALL_USER is present to add the service user to the spi group."""
    txt = _script_text()
    assert 'usermod -aG spi "$INSTALL_USER"' in txt or "usermod -aG spi" in txt, (
        "Missing 'usermod -aG spi' for INSTALL_USER in install.sh"
    )


def test_wrong_tool_not_used_for_spi1():
    """The WRONG tool config-by-hardware.py must NOT be used for SPI1 enablement."""
    txt = _script_text()
    assert "config-by-hardware.py" not in txt, (
        "Must NOT use config-by-hardware.py — use config-by-function.py instead"
    )


def test_config_by_function_used():
    """The correct tool config-by-function.py is used for SPI1 enablement."""
    txt = _script_text()
    assert "config-by-function.py" in txt, (
        "Missing config-by-function.py — must use function-based tool for spi1"
    )


def test_config_by_function_spi1_option():
    """The -o dt spi1 invocation is present (correct overlay option)."""
    txt = _script_text()
    assert "-o dt spi1" in txt, (
        "Missing '-o dt spi1' — must use -o dt for DTB regeneration + boot entry"
    )


def test_idempotency_guard_present():
    """A skip-if-exists check on /dev/spidev0.0 is present."""
    txt = _script_text()
    assert "[ -e /dev/spidev0.0 ]" in txt, (
        "Missing idempotency guard: should skip if /dev/spidev0.0 already exists"
    )


def test_fail_soft_manual_instructions():
    """The jetson-io-absent/error branch prints manual jetson-io.py instructions."""
    txt = _script_text()
    assert "jetson-io.py" in txt, (
        "Missing manual jetson-io.py instructions in fail-soft branch"
    )


def test_fail_soft_no_exit_in_manual_branch():
    """The fail-soft branch (manual-instruction region) must NOT contain 'exit'."""
    txt = _script_text()
    # Locate the fail-soft region: between the manual-instruction echo and its closing fi.
    # Find the jetson-io.py instruction echo, then scan forward to the next 'fi'.
    instr_pos = txt.find("jetson-io.py")
    assert instr_pos > 0, "Could not find jetson-io.py instructions region"

    # Find the enclosing if block — look backward for the nearest 'if' before this line.
    before_instr = txt[:instr_pos]
    last_if = before_instr.rfind("if ")
    assert last_if >= 0, "No enclosing if found before jetson-io.py instructions"

    # Find the matching fi after the instruction region.
    after_instr = txt[instr_pos:]
    next_else_or_fi = min(
        after_instr.find("\nelse"),
        after_instr.find("\nfi"),
    )
    assert next_else_or_fi > 0, "No else/fi found after jetson-io.py instructions"

    fail_soft_region = txt[last_if:instr_pos + next_else_or_fi]
    assert "exit" not in fail_soft_region, (
        "fail-soft branch must NOT contain 'exit' — installer must continue under set -e"
    )


def test_reboot_prompt_present():
    """A 'REBOOT' reboot-required message is surfaced to the operator."""
    txt = _script_text()
    assert "REBOOT" in txt, (
        "Missing REBOOT prompt — operator must be told a reboot is required after SPI1 enable"
    )


def test_spi_step_before_systemd_service():
    """The SPI1-enable step appears BEFORE 'Step 6: Install systemd service'."""
    txt = _script_text()
    spi_pos = txt.find("config-by-function.py")
    step6_pos = txt.find("Step 6: Install systemd service")
    assert spi_pos > 0, "SPI1-enable step (config-by-function.py) not found"
    assert step6_pos > 0, "Step 6: Install systemd service not found"
    assert spi_pos < step6_pos, (
        "SPI1-enable step must appear BEFORE Step 6 (systemd service install)"
    )
