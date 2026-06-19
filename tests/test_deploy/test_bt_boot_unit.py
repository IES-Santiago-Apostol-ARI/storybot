import pathlib


def test_boot_unit_template_contents():
    """Verify the systemd unit template has required tokens and settings."""
    unit_path = pathlib.Path("deploy/storybot-bt-boot.service")
    assert unit_path.exists(), "Unit template file missing"

    content = unit_path.read_text()

    # ExecStart invokes the correct module
    assert "app.bt_boot_reconnect" in content
    # Type is oneshot
    assert "Type=oneshot" in content
    # User is templated
    assert "User=__INSTALL_USER__" in content
    # XDG_RUNTIME_DIR token is present for PipeWire access
    assert "XDG_RUNTIME_DIR=/run/user/__USER_UID__" in content
    # Conflicts with old unit to prevent double-connect
    assert "Conflicts=bluetooth-audio.service" in content


def test_install_sh_wiring():
    """Verify install.sh handles the boot-reconnect unit correctly."""
    script_path = pathlib.Path("deploy/install.sh")
    assert script_path.exists(), "Install script missing"

    content = script_path.read_text()

    # Check for sed substitution of all three tokens. We look for the service file
    # and token substitutions generally in the file.
    assert "storybot-bt-boot.service" in content
    assert "__INSTALL_USER__" in content
    assert "__INSTALL_DIR__" in content
    assert "__USER_UID__" in content

    # Check for systemd enablement
    assert "systemctl enable storybot-bt-boot.service" in content

    # Check for linger enablement
    assert "loginctl enable-linger" in content

    # Check for old unit disarmament
    assert "systemctl disable bluetooth-audio.service" in content
