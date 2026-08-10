"""Tests for the hardware power-key handler (deploy/storybot-powerkey.py).

The handler is a standalone root daemon, not part of the ``app`` package, so it
is loaded by path with importlib. The interesting logic is decoding the KEY
bitmap in /proc/bus/input/devices, which is what these tests pin down.
"""

import importlib.util
import pathlib

import pytest

HANDLER_PATH = pathlib.Path("deploy/storybot-powerkey.py")

# Real /proc/bus/input/devices excerpt from the Jetson Orin Nano carrier board.
# The gpio-keys node carries KEY_POWER (116) and KEY_WAKEUP (257); the
# touchscreen and HDMI audio nodes carry neither.
PROC_DEVICES = """\
I: Bus=0019 Vendor=0001 Product=0001 Version=0100
N: Name="gpio-keys"
P: Phys=gpio-keys/input0
S: Sysfs=/devices/platform/gpio-keys/input/input0
U: Uniq=
H: Handlers=kbd event0
B: PROP=0
B: EV=3
B: KEY=2 0 0 10000000000000 0

I: Bus=0003 Vendor=0eef Product=0005 Version=0100
N: Name="DFRobot USB Multi Touch"
P: Phys=usb-3610000.usb-2.1/input0
S: Sysfs=/devices/platform/3610000.usb/input/input1
U: Uniq=
H: Handlers=event1
B: PROP=2
B: EV=1b
B: KEY=400 0 0 0 0 0

I: Bus=0000 Vendor=0000 Product=0000 Version=0000
N: Name="NVIDIA Jetson Orin Nano HDA HDMI/DP,pcm=3"
P: Phys=ALSA
S: Sysfs=/devices/platform/sound/card0/input3
U: Uniq=
H: Handlers=event3
B: PROP=0
B: EV=21
"""


@pytest.fixture(scope="module")
def handler():
    """Load deploy/storybot-powerkey.py as a module."""
    assert HANDLER_PATH.exists(), "Power-key handler script missing"
    spec = importlib.util.spec_from_file_location("storybot_powerkey", HANDLER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_key_power_constant(handler):
    """KEY_POWER is 116 in the Linux input event codes."""
    assert handler.KEY_POWER == 116
    assert handler.EV_KEY == 1


def test_parse_key_bitmap_low_word(handler):
    """The rightmost word holds bits 0-63; leading zero words are trimmed."""
    # bit 0 set in the low word
    assert handler.parse_key_bitmap("1") == 1
    # bit 64 set: low word zero, next word bit 0
    assert handler.parse_key_bitmap("1 0") == 1 << 64


def test_parse_key_bitmap_gpio_keys(handler):
    """The carrier board's bitmap decodes to KEY_POWER and KEY_WAKEUP."""
    bits = handler.parse_key_bitmap("2 0 0 10000000000000 0")
    assert bits >> handler.KEY_POWER & 1, "KEY_POWER (116) should be set"
    assert bits >> 257 & 1, "KEY_WAKEUP (257) should be set"
    assert not bits >> 30 & 1, "KEY_ENTER (28)/unrelated codes should be clear"


def test_find_power_key_event_picks_gpio_keys(handler):
    """The device carrying KEY_POWER is selected, not the touchscreen."""
    assert handler.find_power_key_event(PROC_DEVICES) == "event0"


def test_find_power_key_event_none_when_absent(handler):
    """Returns None when no input device advertises KEY_POWER."""
    without_gpio_keys = PROC_DEVICES.split("\n\n", 1)[1]
    assert handler.find_power_key_event(without_gpio_keys) is None


def test_find_power_key_event_ignores_non_event_handlers(handler):
    """A device with KEY_POWER but no eventN handler is skipped."""
    text = 'N: Name="odd"\nH: Handlers=kbd\nB: KEY=10000000000000 0\n'
    assert handler.find_power_key_event(text) is None


def test_poweroff_command_is_immediate(handler):
    """Poweroff must ignore inhibitors so no dialog or delay can hold it up."""
    assert handler.POWEROFF_CMD[:2] == ["/bin/systemctl", "poweroff"]
    assert "-i" in handler.POWEROFF_CMD


def test_systemd_unit_contract():
    """The unit runs as root at boot and restarts if the device disappears."""
    unit_path = pathlib.Path("deploy/storybot-powerkey.service")
    assert unit_path.exists(), "Unit file missing"
    content = unit_path.read_text()

    assert "/usr/local/bin/storybot-powerkey.py" in content
    assert "Restart=always" in content
    assert "WantedBy=multi-user.target" in content


def test_dconf_default_disables_gnome_dialog():
    """The dconf fragment must neutralise GNOME's interactive power dialog."""
    dconf_path = pathlib.Path("deploy/dconf-storybot-powerkey")
    assert dconf_path.exists(), "dconf fragment missing"
    content = dconf_path.read_text()

    assert "[org/gnome/settings-daemon/plugins/power]" in content
    assert "power-button-action='nothing'" in content


def test_install_sh_wiring():
    """install.sh installs the handler, the unit, and the dconf override."""
    content = pathlib.Path("deploy/install.sh").read_text()

    assert "install-powerkey.sh" in content


def test_install_powerkey_script_steps():
    """The root installer wires up dconf, the binary, and the unit."""
    script_path = pathlib.Path("deploy/install-powerkey.sh")
    assert script_path.exists(), "Power-key installer missing"
    content = script_path.read_text()

    # dconf system database so the GNOME dialog stays off for every user
    assert "/etc/dconf/profile/user" in content
    assert "system-db:local" in content
    assert "/etc/dconf/db/local.d/00-storybot-powerkey" in content
    assert "dconf update" in content
    # locked so a stray per-user value cannot bring the dialog back
    assert "/etc/dconf/db/local.d/locks/00-storybot-powerkey" in content
    # handler + unit
    assert "/usr/local/bin/storybot-powerkey.py" in content
    assert "systemctl enable" in content
    assert "storybot-powerkey.service" in content


def test_install_powerkey_tolerates_missing_dconf():
    """A headless install without dconf-cli must not abort the whole installer.

    install.sh runs under `set -e` and this script under `set -euo pipefail`, so
    an unguarded `dconf update` on a stories-only box (no GNOME, no dconf-cli)
    would kill the install outright.
    """
    content = pathlib.Path("deploy/install-powerkey.sh").read_text()
    assert "command -v dconf" in content


def test_install_powerkey_installs_daemon_even_without_dconf():
    """The evdev daemon is what actually powers off -- it must not be skipped.

    Guards the ordering: the dconf half is cosmetic (it suppresses the GNOME
    dialog), so it must not sit between the guard and the daemon install.
    """
    content = pathlib.Path("deploy/install-powerkey.sh").read_text()
    daemon_at = content.index("/usr/local/bin/storybot-powerkey.py")
    guard_at = content.index("command -v dconf")
    # The dconf block is guarded, so whatever happens there, the daemon install
    # is still reached.
    assert guard_at < daemon_at, "dconf guard must precede the daemon install"
    assert "systemctl enable --now storybot-powerkey.service" in content
