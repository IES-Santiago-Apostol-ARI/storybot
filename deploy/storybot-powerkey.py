#!/usr/bin/env python3
"""Power off immediately when the hardware power button is pressed.

Ubuntu 22.04's GNOME session owns the carrier board's power key: gsd-media-keys
takes a *block* inhibitor on ``handle-power-key`` (so systemd-logind never sees
it) and, with the stock ``power-button-action='interactive'``, answers a press
with the end-session dialog -- Cancel / Power Off plus a 60 second countdown.
On a kiosk with no keyboard that dialog is a dead end.

GNOME 42 has no ``'shutdown'`` value for that key, and custom keybindings on
XF86PowerOff never fire because the media-keys plugin swallows the key first.
So the dialog is switched off (``power-button-action='nothing'``, shipped as a
locked dconf system default) and this daemon reads the evdev device directly --
below X, so nothing can intercept it -- and powers off on the press edge.

Installed by deploy/install-powerkey.sh as /usr/local/bin/storybot-powerkey.py
and run as root by storybot-powerkey.service.
"""

import os
import re
import struct
import subprocess
import sys
import time

# Linux input event codes (include/uapi/linux/input-event-codes.h)
EV_KEY = 1
KEY_POWER = 116

# ``-i`` ignores inhibitor locks: a stuck GNOME/session inhibitor must never be
# able to reintroduce the delay this daemon exists to remove.
POWEROFF_CMD = ["/bin/systemctl", "poweroff", "-i"]

PROC_DEVICES = "/proc/bus/input/devices"

# struct input_event on 64-bit: time_t sec, suseconds_t usec, u16, u16, s32
EVENT_FORMAT = "llHHi"
EVENT_SIZE = struct.calcsize(EVENT_FORMAT)

# Seconds between rescans while waiting for the input device to appear.
DEVICE_POLL_INTERVAL = 2.0


def parse_key_bitmap(field: str) -> int:
    """Decode a ``B: KEY=`` bitmap from /proc/bus/input/devices into an int.

    The kernel prints the bitmap as space-separated hex words, most significant
    first, trimming leading zero words. So the *rightmost* word holds bits 0-63,
    the one before it bits 64-127, and so on.
    """
    bits = 0
    for index, word in enumerate(reversed(field.split())):
        bits |= int(word, 16) << (64 * index)
    return bits


def find_power_key_event(devices_text: str) -> str | None:
    """Return the ``eventN`` name of the input device that reports KEY_POWER.

    Scanning by capability rather than hardcoding event0 keeps this working if
    device probe order changes and a different node gets the number.
    """
    for block in devices_text.split("\n\n"):
        match = re.search(r"^B: KEY=(.*)$", block, re.MULTILINE)
        if not match:
            continue
        if not parse_key_bitmap(match.group(1)) >> KEY_POWER & 1:
            continue
        handlers = re.search(r"^H: Handlers=(.*)$", block, re.MULTILINE)
        if not handlers:
            continue
        for handler in handlers.group(1).split():
            if handler.startswith("event"):
                return handler
    return None


def wait_for_device() -> str:
    """Block until the KEY_POWER device exists, then return its /dev path."""
    while True:
        try:
            with open(PROC_DEVICES) as handle:
                event = find_power_key_event(handle.read())
        except OSError:
            event = None
        if event is not None:
            path = os.path.join("/dev/input", event)
            if os.path.exists(path):
                return path
        time.sleep(DEVICE_POLL_INTERVAL)


def main() -> int:
    device = wait_for_device()
    print(f"watching {device} for KEY_POWER", flush=True)

    with open(device, "rb") as handle:
        while True:
            data = handle.read(EVENT_SIZE)
            if not data or len(data) < EVENT_SIZE:
                # Device went away -- exit non-zero so systemd restarts us and
                # we rediscover the node.
                print("input device closed", file=sys.stderr, flush=True)
                return 1
            _sec, _usec, etype, code, value = struct.unpack(EVENT_FORMAT, data)
            # value 1 == press. Act on the press edge, not the release, so the
            # button feels instant.
            if etype == EV_KEY and code == KEY_POWER and value == 1:
                print("power key pressed -- powering off", flush=True)
                subprocess.Popen(POWEROFF_CMD)
                return 0


if __name__ == "__main__":
    sys.exit(main())
