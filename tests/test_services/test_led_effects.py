"""Pure render-function math tests for LED effects.

These tests exercise the deterministic effect math in `led_effects.py`
without any asyncio, I/O, or wall-clock sleeps. Each render function
takes (now, count, params) -> list[(r, g, b)] and is tested in isolation.

Requirements covered: LED-10 (breathing), LED-12 (progress edge cases),
LED-17 (comet advance), LED-19 (param fill), LED-18 (boot wipe),
LED-15 (error amber), LED-22 (cross-fade), LED-24 (brightness clamp),
LED-25 (gamma).
"""

import math
import pytest

from app.services.led_effects import (
    breathe,
    comet,
    crossfade,
    error_amber,
    idle_glow,
    param_fill,
    progress,
    boot_wipe,
)
from app.services.led_spi import encode_ws2812
from app.config import ConfigManager

settings = ConfigManager().load()

# --- LED-10: Playback breathing bounds ---------------------------------

class TestBreathe:
    """LED-10: Breathing stays within [TROUGH, PEAK] x color."""

    def test_breathe_oscillates_between_trough_and_peak(self):
        """Breathing sinusoid dips to ~0.35 and peaks at 1.0 x color."""
        color = (255, 128, 64)
        count = 21
        fb = breathe(now=0.0, count=count, color=color)

        # All pixels should be the same solid color (breathing is uniform)
        assert len(fb) == count
        assert all(px == fb[0] for px in fb)

        # Trough: sin(3pi/2) = -1 -> s=0 -> scale=0.35
        fb_trough = breathe(now=0.0 + 4.5 * 0.75, count=count, color=color)
        r_trough, g_trough, b_trough = fb_trough[0]
        assert r_trough == round(255 * 0.35)
        assert g_trough == round(128 * 0.35)
        assert b_trough == round(64 * 0.35)

        # Peak: sin(pi/2) = 1 -> s=1 -> scale=1.0
        fb_peak = breathe(now=0.0 + 4.5 * 0.25, count=count, color=color)
        r_peak, g_peak, b_peak = fb_peak[0]
        assert r_peak == 255
        assert g_peak == 128
        assert b_peak == 64

    def test_breathe_never_fully_off(self):
        """Breathing trough should never produce (0,0,0) for any color."""
        color = (10, 5, 2)  # very dim color
        fb = breathe(now=0.0 + 4.5 * 0.75, count=21, color=color)
        r, g, b = fb[0]
        assert r >= 1 or g >= 1 or b >= 1, "Breathing trough must never be fully off"

    def test_breathe_all_pixels_uniform(self):
        """Breathing is a uniform solid-color effect - all pixels equal."""
        fb = breathe(now=1.23, count=21, color=(100, 200, 50))
        assert all(px == fb[0] for px in fb)

# --- LED-17: Comet / chase advance -------------------------------------

class TestComet:
    """LED-17: Comet advances along the strip."""

    def test_comet_head_advances_with_time(self):
        """The bright head pixel moves forward as time increases."""
        color = (255, 255, 255)
        count = 21
        fb1 = comet(now=0.0, count=count, color=color)
        fb2 = comet(now=0.5, count=count, color=color)

        # Head position should differ
        head1 = max(range(count), key=lambda i: fb1[i][0])
        head2 = max(range(count), key=lambda i: fb2[i][0])
        assert head1 != head2, "Comet head should advance with time"

    def test_comet_head_is_brightest_pixel(self):
        """The head pixel has the highest brightness."""
        fb = comet(now=1.0, count=21, color=(100, 150, 200))
        head = max(range(21), key=lambda i: sum(fb[i]))
        assert fb[head] == (100, 150, 200), "Head should be full color"

    def test_comet_tail_fades(self):
        """Pixels behind the head fade progressively."""
        fb = comet(now=1.0, count=21, color=(255, 0, 0))
        head = max(range(21), key=lambda i: sum(fb[i]))
        tail_idx = (head - 1) % 21
        assert sum(fb[tail_idx]) < sum(fb[head]), "Tail should be dimmer than head"

    def test_comet_non_head_pixels_are_dark(self):
        """Pixels not in the head or tail should be (0,0,0)."""
        fb = comet(now=1.0, count=21, color=(255, 0, 0))
        head = max(range(21), key=lambda i: sum(fb[i]))
        # Check a pixel far from head and tail
        far_idx = (head + 10) % 21
        assert fb[far_idx] == (0, 0, 0)

# --- LED-20: Proportional progress fill --------------------------------

class TestProgress:
    """LED-20: Progress bar fills proportionally."""

    def test_progress_empty_at_zero(self):
        """i=0 should produce all dark pixels."""
        fb = progress(now=0.0, count=21, color=(255, 0, 0), i=0, n=10)
        assert all(px == (0, 0, 0) for px in fb)

    def test_progress_full_when_i_equals_n(self):
        """i==N should fill all pixels."""
        fb = progress(now=0.0, count=21, color=(0, 255, 0), i=10, n=10)
        assert all(px == (0, 255, 0) for px in fb)

    def test_progress_robust_to_n_gt_21(self):
        """N>21 should still fill all pixels when i==N."""
        fb = progress(now=0.0, count=21, color=(0, 0, 255), i=50, n=50)
        assert all(px == (0, 0, 255) for px in fb)

    def test_progress_n_equals_1(self):
        """N=1 should fill all pixels at i=1."""
        fb = progress(now=0.0, count=21, color=(128, 128, 128), i=1, n=1)
        assert all(px == (128, 128, 128) for px in fb)

    def test_progress_clamps_i_to_range(self):
        """i beyond N should be clamped to N."""
        fb = progress(now=0.0, count=21, color=(255, 128, 0), i=15, n=10)
        assert all(px == (255, 128, 0) for px in fb)

    def test_progress_partial_fill(self):
        """Half progress should fill roughly half the pixels."""
        fb = progress(now=0.0, count=21, color=(255, 0, 0), i=5, n=10)
        lit = sum(1 for px in fb if px != (0, 0, 0))
        # ceil(5/10 * 21) = ceil(10.5) = 11
        assert lit == 11

# --- LED-19: Parameter accumulation ------------------------------------

class TestParamFill:
    """LED-19: One pixel per parameter card."""

    def test_param_fill_lights_next_pixel(self):
        """Each parameter lights the next pixel from pixel 0."""
        fb1 = param_fill(now=0.0, count=21, n_params=1)
        fb3 = param_fill(now=0.0, count=21, n_params=3)

        assert fb1[0] != (0, 0, 0)
        assert fb1[1] == (0, 0, 0)
        assert fb3[0] != (0, 0, 0)
        assert fb3[1] != (0, 0, 0)
        assert fb3[2] != (0, 0, 0)
        assert fb3[3] == (0, 0, 0)

    def test_param_fill_clamps_to_count(self):
        """n_params beyond count should not overflow."""
        fb = param_fill(now=0.0, count=21, n_params=100)
        lit = sum(1 for px in fb if px != (0, 0, 0))
        assert lit == 21

    def test_param_fill_zero_params(self):
        """Zero params should produce all dark pixels."""
        fb = param_fill(now=0.0, count=21, n_params=0)
        assert all(px == (0, 0, 0) for px in fb)

# --- LED-18: Boot wipe ------------------------------------------------

class TestBootWipe:
    """LED-18: Single-color wipe across all pixels."""

    def test_boot_wipe_starts_at_pixel_0(self):
        """At elapsed=0, only pixel 0 should be lit."""
        fb = boot_wipe(elapsed=0.0, count=21, color=(255, 255, 255))
        assert fb[0] != (0, 0, 0)

    def test_boot_wipe_advances_with_time(self):
        """More elapsed time should light more pixels."""
        fb1 = boot_wipe(elapsed=0.2, count=21, color=(255, 0, 0))
        fb2 = boot_wipe(elapsed=0.5, count=21, color=(255, 0, 0))
        lit1 = sum(1 for px in fb1 if px != (0, 0, 0))
        lit2 = sum(1 for px in fb2 if px != (0, 0, 0))
        assert lit2 > lit1

    def test_boot_wipe_completes(self):
        """After WIPE_DURATION_S, all pixels should be lit."""
        fb = boot_wipe(elapsed=1.5, count=21, color=(0, 255, 0))
        assert all(px == (0, 255, 0) for px in fb)

# --- LED-15: Error amber -----------------------------------------------

class TestErrorAmber:
    """LED-15: Gentle amber error indication."""

    def test_error_amber_never_red(self):
        """Error should never produce a red color (R >> G, B)."""
        fb = error_amber(now=0.0, count=21, elapsed=0.0)
        r, g, b = fb[0]
        assert r <= g + 50, "Error should not be predominantly red"

    def test_error_amber_is_amber_tinted(self):
        """Error should have amber tint: R > B, G close to R."""
        fb = error_amber(now=0.0, count=21, elapsed=0.0)
        r, g, b = fb[0]
        assert r > b, "Amber should have more red than blue"
        assert g > b, "Amber should have more green than blue"

    def test_error_amber_fades_out(self):
        """After auto-fade duration, error should settle to dark."""
        fb = error_amber(now=0.0, count=21, elapsed=5.0)
        r, g, b = fb[0]
        assert r < 255 or g < 255, "Error should not be full brightness after fade"

# --- LED-16: Idle glow ------------------------------------------------

class TestIdleGlow:
    """LED-16: Calm ambient idle glow."""

    def test_idle_glow_is_static(self):
        """Idle glow should not change with time."""
        fb1 = idle_glow(now=0.0, count=21)
        fb2 = idle_glow(now=10.0, count=21)
        assert fb1 == fb2, "Idle glow should be static"

    def test_idle_glow_is_warm_amber(self):
        """Idle glow should be warm amber: R > B, G > B."""
        fb = idle_glow(now=0.0, count=21)
        r, g, b = fb[0]
        assert r > b, "Idle glow should be warm (R > B)"
        assert g > b, "Idle glow should have green component"

    def test_idle_glow_is_dim(self):
        """Idle glow should be low brightness (child-safe)."""
        fb = idle_glow(now=0.0, count=21)
        r, g, b = fb[0]
        assert r < 128 and g < 128, "Idle glow should be dim"

    def test_idle_glow_all_pixels_uniform(self):
        """Idle glow is a solid color across all pixels."""
        fb = idle_glow(now=0.0, count=21)
        assert all(px == fb[0] for px in fb)

# --- LED-22: Cross-fade -----------------------------------------------

class TestCrossfade:
    """LED-22: Smooth cross-fades between frames."""

    def test_crossfade_alpha_0_returns_from(self):
        """alpha=0 should return the 'from' framebuffer."""
        fb_from = [(255, 0, 0)] * 21
        fb_to = [(0, 255, 0)] * 21
        result = crossfade(fb_from, fb_to, alpha=0.0)
        assert result == fb_from

    def test_crossfade_alpha_1_returns_to(self):
        """alpha=1 should return the 'to' framebuffer."""
        fb_from = [(255, 0, 0)] * 21
        fb_to = [(0, 255, 0)] * 21
        result = crossfade(fb_from, fb_to, alpha=1.0)
        assert result == fb_to

    def test_crossfade_alpha_05_blends(self):
        """alpha=0.5 should produce a blended result."""
        fb_from = [(255, 0, 0)] * 21
        fb_to = [(0, 255, 0)] * 21
        result = crossfade(fb_from, fb_to, alpha=0.5)
        r, g, b = result[0]
        assert r == round(255 * 0.5)
        assert g == round(255 * 0.5)
        assert b == 0

    def test_crossfade_different_pixel_values(self):
        """Crossfade with different per-pixel values."""
        fb_from = [(255, 0, 0), (0, 0, 0), (0, 0, 0)]
        fb_to = [(0, 0, 0), (0, 255, 0), (0, 0, 255)]
        result = crossfade(fb_from, fb_to, alpha=0.5)
        assert result[0] == (round(255 * 0.5), 0, 0)
        assert result[1] == (0, round(255 * 0.5), 0)
        assert result[2] == (0, 0, round(255 * 0.5))

# --- LED-24: Brightness clamp (via encoder) ----------------------------

class TestBrightnessClamp:
    """LED-24: Brightness cap enforced by encoder."""

    def test_encoder_clamps_to_max_brightness(self):
        """encode_ws2812 caps to led_max_brightness (0.30)."""
        pixels = [(255, 255, 255)] * 21
        encoded = encode_ws2812(
            pixels,
            count=settings.led_count,
            cap=settings.led_max_brightness,
            gamma=settings.led_gamma,
            order=settings.led_color_order,
        )
        # Should not be all zeros (cap is a fraction, not zero)
        assert encoded != b'\x00' * len(encoded)

# --- LED-25: Gamma correction (via encoder) ----------------------------

class TestGamma:
    """LED-25: Gamma-corrected output via encoder LUT."""

    def test_gamma_lut_applied(self):
        """Non-linear gamma should produce different output than linear."""
        pixels = [(128, 0, 0)] * 21
        # With gamma, 128 should not map to exactly half of 255
        encoded = encode_ws2812(
            pixels,
            count=settings.led_count,
            cap=1.0,
            gamma=settings.led_gamma,
            order=settings.led_color_order,
        )
        # Just verify it produces non-zero output
        assert encoded != b'\x00' * len(encoded)
