"""Tests for Phase 31 LED config fields (LED-03) — all 7 LED tunables present in Settings, stale led_strip_device serial default removed (D-06), content/config.json tolerates the stale key (RESEARCH A4)."""

from app.config import ConfigManager, Settings


class TestLedConfig:
    """Tests for LED-specific configuration fields."""

    def test_led_count_default(self):
        """Settings().led_count defaults to 21 (D-10)."""
        assert Settings().led_count == 21

    def test_led_max_brightness_default(self):
        """Settings().led_max_brightness defaults to 0.30 (D-09)."""
        assert Settings().led_max_brightness == 0.30

    def test_led_spi_bus_default(self):
        """Settings().led_spi_bus defaults to 0 (D-12)."""
        assert Settings().led_spi_bus == 0

    def test_led_spi_dev_default(self):
        """Settings().led_spi_dev defaults to 0 (D-12)."""
        assert Settings().led_spi_dev == 0

    def test_led_spi_speed_hz_default(self):
        """Settings().led_spi_speed_hz defaults to 6,400,000 (D-11)."""
        assert Settings().led_spi_speed_hz == 6_400_000

    def test_led_color_order_default(self):
        """Settings().led_color_order defaults to 'GRB' (D-13)."""
        assert Settings().led_color_order == "GRB"

    def test_led_gamma_default(self):
        """Settings().led_gamma defaults to 2.2."""
        assert Settings().led_gamma == 2.2

    def test_stale_serial_default_removed(self):
        """Settings no longer contains the stale led_strip_device field (D-06)."""
        assert not hasattr(Settings(), "led_strip_device")

    def test_config_json_stale_key_tolerated(self):
        """ConfigManager().load() tolerates the stale led_strip_device key in content/config.json (RESEARCH A4)."""
        # The real ConfigManager defaults to content/config.json, which contains the stale key
        settings = ConfigManager().load()
        assert isinstance(settings, Settings)
        assert settings.led_count == 21

    # --- Phase 33 effect tunables (LED-10, LED-15, LED-16, LED-17, LED-19, LED-24) ---

    def test_led_breathe_period_s_default(self):
        """Settings().led_breathe_period_s defaults to 4.5 (D-06)."""
        assert Settings().led_breathe_period_s == 4.5

    def test_led_breathe_trough_default(self):
        """Settings().led_breathe_trough defaults to 0.35, within [0.30, 0.40] (D-06)."""
        s = Settings()
        assert 0.30 <= s.led_breathe_trough <= 0.40

    def test_led_comet_period_s_default(self):
        """Settings().led_comet_period_s defaults to 2.0 (D-08)."""
        assert Settings().led_comet_period_s == 2.0

    def test_led_comet_tail_default(self):
        """Settings().led_comet_tail defaults to 3 (D-08)."""
        assert Settings().led_comet_tail == 3

    def test_led_idle_color_default(self):
        """Settings().led_idle_color is a valid 6-digit hex string (D-07)."""
        s = Settings()
        assert s.led_idle_color.startswith("#")
        assert len(s.led_idle_color) == 7

    def test_led_error_color_default(self):
        """Settings().led_error_color is a valid 6-digit hex amber string (D-09)."""
        s = Settings()
        assert s.led_error_color.startswith("#")
        assert len(s.led_error_color) == 7

    def test_led_accum_color_default(self):
        """Settings().led_accum_color is a valid 6-digit hex string (D-20)."""
        s = Settings()
        assert s.led_accum_color.startswith("#")
        assert len(s.led_accum_color) == 7

    def test_led_boot_wipe_s_default(self):
        """Settings().led_boot_wipe_s defaults to 1.0 (D-10)."""
        assert Settings().led_boot_wipe_s == 1.0

    def test_led_crossfade_s_default(self):
        """Settings().led_crossfade_s defaults to 0.5 (D-17)."""
        assert Settings().led_crossfade_s == 0.5
