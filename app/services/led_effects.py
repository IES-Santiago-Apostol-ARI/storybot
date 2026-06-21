"""Pure render-function math for LED effects.

Each function takes (now, count, **params) -> list[(r, g, b)] and returns a
framebuffer of exactly `count` pixels. No I/O, no asyncio, no wall-clock
sleeps — just deterministic math.

Requirements covered:
  LED-10: breathe (playback breathing)
  LED-15: error_amber (gentle amber error)
  LED-16: idle_glow (calm ambient idle)
  LED-18: boot_wipe (single-color wipe)
  LED-19: param_fill (one pixel per parameter card)
  LED-20: progress (proportional progress bar)
  LED-22: crossfade (smooth cross-fade between frames)
  LED-24: brightness cap enforced by encoder (not here)
  LED-25: gamma enforced by encoder (not here)
"""

import math

# --- Constants -----------------------------------------------------------

# LED-10: breathing sinusoid
_BREATHE_PERIOD = 4.5  # seconds per full cycle
_BREATHE_TROUGH = 0.35  # minimum brightness fraction

# LED-15: error amber — warm amber, not red-dominant
_ERROR_AMBER_COLOR = (180, 140, 0)  # amber, R <= G + 50
_ERROR_AMBER_DURATION = 3.0  # seconds before fade-out
_ERROR_AMBER_FADE = 1.0  # fade duration

# LED-16: idle glow
_IDLE_GLOW_COLOR = (64, 48, 0)  # warm amber, dim

# LED-18: boot wipe
_WIPE_DURATION_S = 1.0  # seconds to wipe across all pixels

# LED-17: comet
_COMET_SPEED = 4.0  # pixels per second
_COMET_TAIL_LEN = 3  # number of tail pixels

# LED-19: param fill
_PARAM_FILL_COLOR = (0, 255, 128)  # teal

# LED-20: progress
_PROGRESS_COLOR = (0, 200, 255)  # cyan


def breathe(now: float, count: int, color: tuple[int, int, int]) -> list[tuple[int, int, int]]:
    """LED-10: Breathing sinusoid — uniform solid color across all pixels.

    Oscillates between [_BREATHE_TROUGH, 1.0] * color.
    """
    s = (math.sin(2 * math.pi * now / _BREATHE_PERIOD) + 1.0) / 2.0  # [0, 1]
    scale = _BREATHE_TROUGH + (1.0 - _BREATHE_TROUGH) * s  # [_BREATHE_TROUGH, 1.0]
    r = round(color[0] * scale)
    g = round(color[1] * scale)
    b = round(color[2] * scale)
    return [(r, g, b)] * count


def comet(now: float, count: int, color: tuple[int, int, int]) -> list[tuple[int, int, int]]:
    """LED-17: Comet / chase — bright head pixel advancing along the strip.

    Head position advances with time. Tail pixels fade progressively.
    """
    head = int(now * _COMET_SPEED) % count
    fb = [(0, 0, 0)] * count
    for i in range(count):
        dist = (i - head) % count
        if dist == 0:
            fb[i] = color
        elif dist <= _COMET_TAIL_LEN:
            fade = 1.0 - (dist / (_COMET_TAIL_LEN + 1))
            fb[i] = (
                round(color[0] * fade),
                round(color[1] * fade),
                round(color[2] * fade),
            )
    return fb


def progress(now: float, count: int, color: tuple[int, int, int],
             i: int, n: int) -> list[tuple[int, int, int]]:
    """LED-20: Proportional progress bar fill.

    i = current step, n = total steps. Fills pixels from left to right.
    """
    if n <= 0:
        return [(0, 0, 0)] * count
    ratio = min(i / n, 1.0)
    filled = math.ceil(ratio * count)
    return [color] * filled + [(0, 0, 0)] * (count - filled)


def param_fill(now: float, count: int, n_params: int) -> list[tuple[int, int, int]]:
    """LED-19: One pixel per parameter card, filling from pixel 0.

    Lights n_params pixels in _PARAM_FILL_COLOR.
    """
    lit = min(n_params, count)
    return [_PARAM_FILL_COLOR] * lit + [(0, 0, 0)] * (count - lit)


def boot_wipe(elapsed: float, count: int, color: tuple[int, int, int]) -> list[tuple[int, int, int]]:
    """LED-18: Single-color wipe across all pixels.

    At elapsed=0, only pixel 0 is lit. After _WIPE_DURATION_S, all pixels are lit.
    """
    ratio = min(elapsed / _WIPE_DURATION_S, 1.0)
    filled = max(1, math.ceil(ratio * count))
    return [color] * filled + [(0, 0, 0)] * (count - filled)


def error_amber(now: float, count: int, elapsed: float) -> list[tuple[int, int, int]]:
    """LED-15: Gentle amber error indication.

    Amber color (255, 140, 0) for _ERROR_AMBER_DURATION seconds, then fades out.
    """
    if elapsed <= _ERROR_AMBER_DURATION:
        return [_ERROR_AMBER_COLOR] * count
    fade_elapsed = elapsed - _ERROR_AMBER_DURATION
    fade_ratio = max(0.0, 1.0 - fade_elapsed / _ERROR_AMBER_FADE)
    r = round(_ERROR_AMBER_COLOR[0] * fade_ratio)
    g = round(_ERROR_AMBER_COLOR[1] * fade_ratio)
    b = round(_ERROR_AMBER_COLOR[2] * fade_ratio)
    return [(r, g, b)] * count


def idle_glow(now: float, count: int) -> list[tuple[int, int, int]]:
    """LED-16: Calm ambient idle glow.

    Static warm amber color, low brightness.
    """
    return [_IDLE_GLOW_COLOR] * count


def crossfade(fb_from: list[tuple[int, int, int]],
              fb_to: list[tuple[int, int, int]],
              alpha: float) -> list[tuple[int, int, int]]:
    """LED-22: Smooth cross-fade between two frames.

    alpha=0 -> from, alpha=1 -> to. Blends per-pixel.
    """
    alpha = max(0.0, min(1.0, alpha))
    result = []
    for (r1, g1, b1), (r2, g2, b2) in zip(fb_from, fb_to):
        r = round(r1 * (1.0 - alpha) + r2 * alpha)
        g = round(g1 * (1.0 - alpha) + g2 * alpha)
        b = round(b1 * (1.0 - alpha) + b2 * alpha)
        result.append((r, g, b))
    return result
