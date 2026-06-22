#!/usr/bin/env python3
"""Standalone WS2812B strip self-test for StoryBot.

Drives the real LED strip directly through the project's own encoder
(app.services.led_spi) and config (app.config), bypassing the FastAPI app.
Use it on the Jetson to confirm the strip works and to locate a dead pixel.

Run on the Jetson (aarch64, strip wired to SPI1 / header pin 19 = MOSI):

    uv run python deploy/led_selftest.py            # full sweep
    uv run python deploy/led_selftest.py --test fill # just the dead-pixel finder
    uv run python deploy/led_selftest.py --bright    # full brightness (ignore the 0.30 cap)

Tests (see --test):
    solids  Solid red/green/blue/white. Checks channels + color order (GRB).
    walk    Lights one pixel at a time, 0..N. Watch where it stops/garbles.
    fill    Cumulative fill 0..i. The step where the count stops growing = dead pixel.
    ramp    Brightness 0->100% white. Smooth fade = good signal + power.
    prod    Blue at the configured cap/gamma (what the app actually shows).

Diagnosis cheatsheet:
    - Stops at the SAME pixel every run, low brightness doesn't help -> dead pixel
      / cold solder joint at that index (DOUT broken). Re-solder or cut+bridge it.
    - More pixels light at low brightness than at full white -> power sag; inject
      5 V at the far end or use a thicker/shorter supply wire.
    - Boundary wanders between runs -> marginal 3.3 V logic level; add a level
      shifter (74AHCT125) or run the strip at ~4.5 V.
    - Colors swapped (red<->green) -> wrong color order; fix led_color_order.
"""

from __future__ import annotations

import argparse
import time

from app.config import ConfigManager
from app.services.led_spi import SpiWriter, encode_ws2812

settings = ConfigManager().load()


def _make_writer() -> SpiWriter:
    return SpiWriter(
        bus=settings.led_spi_bus,
        dev=settings.led_spi_dev,
        speed_hz=settings.led_spi_speed_hz,
    )


def _hold(writer: SpiWriter, pixels, secs: float, *, cap: float, gamma: float) -> None:
    """Re-stream a frame for `secs` so the strip latches reliably while you watch."""
    end = time.time() + secs
    frame = encode_ws2812(
        pixels,
        count=settings.led_count,
        cap=cap,
        gamma=gamma,
        order=settings.led_color_order,
        speed_hz=settings.led_spi_speed_hz,
    )
    while time.time() < end:
        writer.write(frame)
        time.sleep(0.02)


def _off(writer: SpiWriter) -> None:
    _hold(writer, [(0, 0, 0)] * settings.led_count, 0.1, cap=1.0, gamma=1.0)


def test_solids(w: SpiWriter, cap: float, gamma: float) -> None:
    n = settings.led_count
    for name, rgb in [
        ("RED", (255, 0, 0)),
        ("GREEN", (0, 255, 0)),
        ("BLUE", (0, 0, 255)),
        ("WHITE", (255, 255, 255)),
    ]:
        print(f"  [solids] {name}")
        _hold(w, [rgb] * n, 2.5, cap=cap, gamma=gamma)


def test_walk(w: SpiWriter, cap: float, gamma: float) -> None:
    n = settings.led_count
    print("  [walk] one pixel at a time -> note the first dark/yellow index")
    for i in range(n):
        frame = [(0, 0, 0)] * n
        frame[i] = (255, 255, 255)
        print(f"    -> LED {i}")
        _hold(w, frame, 0.6, cap=cap, gamma=gamma)


def test_fill(w: SpiWriter, cap: float, gamma: float) -> None:
    n = settings.led_count
    print("  [fill] cumulative 0..i -> the step where the count stops growing = dead pixel")
    for i in range(n):
        frame = [(255, 255, 255)] * (i + 1) + [(0, 0, 0)] * (n - i - 1)
        print(f"    -> first {i + 1} LEDs ON (indices 0..{i})")
        _hold(w, frame, 1.0, cap=cap, gamma=gamma)


def test_ramp(w: SpiWriter, cap: float, gamma: float) -> None:
    n = settings.led_count
    print("  [ramp] 0->100% white (smooth fade = good)")
    for lvl in range(0, 256, 8):
        _hold(w, [(lvl, lvl, lvl)] * n, 0.06, cap=cap, gamma=gamma)


def test_prod(w: SpiWriter, cap: float, gamma: float) -> None:
    n = settings.led_count
    print(
        f"  [prod] blue at configured cap={settings.led_max_brightness} "
        f"gamma={settings.led_gamma} (what the app shows)"
    )
    _hold(
        w,
        [(0, 0, 255)] * n,
        3.0,
        cap=settings.led_max_brightness,
        gamma=settings.led_gamma,
    )


TESTS = {
    "solids": test_solids,
    "walk": test_walk,
    "fill": test_fill,
    "ramp": test_ramp,
    "prod": test_prod,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="StoryBot WS2812B strip self-test.")
    parser.add_argument(
        "--test",
        choices=[*TESTS, "all"],
        default="all",
        help="Which test to run (default: all).",
    )
    parser.add_argument(
        "--bright",
        action="store_true",
        help="Use full brightness/linear gamma for max visibility "
        "(ignores the child-safe 0.30 cap). 'prod' always uses configured values.",
    )
    args = parser.parse_args()

    # Visibility settings for the diagnostic tests (prod uses configured values).
    cap = 1.0 if args.bright else settings.led_max_brightness
    gamma = 1.0 if args.bright else settings.led_gamma

    print(
        f"config: count={settings.led_count} bus={settings.led_spi_bus} "
        f"dev={settings.led_spi_dev} speed={settings.led_spi_speed_hz} "
        f"order={settings.led_color_order}"
    )
    print(f"test={args.test} bright={args.bright} (cap={cap} gamma={gamma})\n")

    selected = TESTS.values() if args.test == "all" else [TESTS[args.test]]

    w = _make_writer()
    try:
        for fn in selected:
            fn(w, cap, gamma)
    finally:
        _off(w)
        w.close()
    print("\n=== done — strip cleared ===")


if __name__ == "__main__":
    main()
