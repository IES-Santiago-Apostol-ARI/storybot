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
