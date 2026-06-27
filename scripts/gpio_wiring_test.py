#!/usr/bin/env python3
"""Standalone GPIO wiring test for all four buttons (run ON the Jetson).

Verifies the physical wiring + edge detection for every StoryBot button at
once, independent of the FastAPI app. Use it to confirm each button is on the
pin you think it is and that a press registers cleanly.

Pin map and timings mirror app/config.py Settings (BOARD mode, PUD_DOWN,
RISING edge) but are duplicated here as plain constants on purpose: this
script must run on the Jetson's *system* python3 (where Jetson.GPIO lives as
an apt package), which has no access to the project venv / pydantic. Keep
these values in sync with app/config.py if the pins ever change.

Usage (on the Jetson, NOT the dev machine):

    sudo python3 scripts/gpio_wiring_test.py            # active-high (default)
    sudo python3 scripts/gpio_wiring_test.py --invert   # buttons wired to GND

It does three things:
  1. Reports whether the app would pick the Real or Mock GPIO service.
  2. Polls the raw level on all four pins so you can confirm wiring:
     released -> 0, pressed -> 1  (active-high, internal pull-down).
  3. Arms edge detection on all four pins exactly like gpio_handler.py
     and prints which button fired, so you can check each one is mapped right.

Wiring modes:
  default      buttons wired to 3.3V; internal pull-DOWN; press = HIGH; RISING
               edge. This is what gpio_handler.py uses in production.
  --invert     buttons wired to GND; internal pull-UP; press = LOW; FALLING
               edge. Use this to confirm a button works when it's wired the
               other way (then fix the wiring to match production, or the pin
               will never fire in the real app).
"""

import os
import platform
import sys
import time

# Button name -> BOARD pin. Mirrors app/config.py Settings defaults.
# Duplicated (not imported) so this runs on the Jetson's system python3.
PIN_MAP = {
    "power": 7,
    "interrupt": 15,
    "image": 29,
    "animation": 31,
}
BOUNCE_MS = 200  # Settings.gpio_bounce_ms


def report_service_choice() -> None:
    print("== service selection probe ==")
    print(f"  platform.machine()   = {platform.machine()!r}")
    print(f"  TESTING env set      = {bool(os.environ.get('TESTING'))}")
    try:
        import Jetson.GPIO  # noqa: F401

        print("  import Jetson.GPIO   = OK")
    except Exception as e:  # pragma: no cover
        print(f"  import Jetson.GPIO   = FAILED ({e})")
    print()
    print("== pin map (BOARD numbering) ==")
    for name, pin in PIN_MAP.items():
        print(f"  {name:<10} -> pin {pin}")
    print()


def main() -> int:
    invert = "--invert" in sys.argv[1:]

    report_service_choice()

    try:
        import Jetson.GPIO as GPIO
    except Exception as e:
        print(f"Cannot import Jetson.GPIO: {e}", file=sys.stderr)
        return 1

    pin_to_name = {pin: name for name, pin in PIN_MAP.items()}

    # Wiring mode: default = pull-down + RISING (production); --invert = pull-up
    # + FALLING (buttons to GND).
    pull = GPIO.PUD_UP if invert else GPIO.PUD_DOWN
    edge = GPIO.FALLING if invert else GPIO.RISING
    pressed_level = 0 if invert else 1
    mode_label = (
        "--invert (pull-up, to GND)" if invert else "default (pull-down, to 3.3V)"
    )

    GPIO.setwarnings(True)
    GPIO.setmode(GPIO.BOARD)
    for pin in PIN_MAP.values():
        GPIO.setup(pin, GPIO.IN, pull_up_down=pull)

    print(f"== wiring mode: {mode_label} ==\n")
    print("== raw level poll on all pins (Ctrl-C to move on) ==")
    print(
        f"   Expect {1 - pressed_level} when released, "
        f"{pressed_level} while you hold a button."
    )
    print("   Press each button in turn and watch its column flip.")
    header = "   " + "  ".join(f"{name}({pin})" for name, pin in PIN_MAP.items())
    print(header)
    try:
        while True:
            cols = "  ".join(
                f"{name}({pin})={GPIO.input(pin)}" for name, pin in PIN_MAP.items()
            )
            print(f"   {cols}   ", end="\r", flush=True)
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n")

    presses = {name: 0 for name in PIN_MAP}

    edge_label = "FALLING" if invert else "RISING"

    def _cb(channel: int) -> None:
        name = pin_to_name.get(channel, "?")
        presses[name] += 1
        print(
            f"   {edge_label} edge: {name:<10} (pin {channel})  count={presses[name]}"
        )

    print(f"== edge detection armed ({edge_label}, bounce={BOUNCE_MS}ms) ==")
    print("   Press each button a few times. Ctrl-C to exit.")
    for pin in PIN_MAP.values():
        GPIO.add_event_detect(pin, edge, callback=_cb, bouncetime=BOUNCE_MS)
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        GPIO.cleanup()

    print("\n== summary ==")
    for name, pin in PIN_MAP.items():
        status = "OK" if presses[name] else "NO PRESS DETECTED"
        print(f"  {name:<10} (pin {pin}): {presses[name]} edges  [{status}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
