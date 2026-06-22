"""Tests for Phase 35 GPIO config defaults (GPIO-04) and Jetson.GPIO dep declaration (SETUP-02)."""

from pathlib import Path

import tomli

from app.config import Settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PYPROJECT_TOML = PROJECT_ROOT / "pyproject.toml"


class TestGpioConfig:
    """Tests for GPIO-specific configuration fields."""

    def test_gpio_power_pin_default(self):
        """Settings().gpio_power_pin defaults to 7 (GPIO-04)."""
        assert Settings().gpio_power_pin == 7

    def test_gpio_interrupt_pin_default(self):
        """Settings().gpio_interrupt_pin defaults to 15 (GPIO-04)."""
        assert Settings().gpio_interrupt_pin == 15

    def test_gpio_image_pin_default(self):
        """Settings().gpio_image_pin defaults to 29 (GPIO-04)."""
        assert Settings().gpio_image_pin == 29

    def test_gpio_animation_pin_default(self):
        """Settings().gpio_animation_pin defaults to 31 (GPIO-04)."""
        assert Settings().gpio_animation_pin == 31

    def test_gpio_debounce_ms_default(self):
        """Settings().gpio_debounce_ms defaults to 50 (GPIO-04)."""
        assert Settings().gpio_debounce_ms == 50

    def test_gpio_poll_interval_s_default(self):
        """Settings().gpio_poll_interval_s defaults to 0.02 (GPIO-04)."""
        assert Settings().gpio_poll_interval_s == 0.02

    def test_poweroff_cmd_default(self):
        """Settings().poweroff_cmd defaults to ['/usr/bin/sudo', '/sbin/poweroff'] (GPIO-04)."""
        assert Settings().poweroff_cmd == ["/usr/bin/sudo", "/sbin/poweroff"]

    def test_gpio_enabled_default(self):
        """Settings().gpio_enabled defaults to True (GPIO-04)."""
        assert Settings().gpio_enabled is True

    def test_jetson_gpio_dep_declared(self):
        """pyproject.toml jetson extra contains Jetson.GPIO with aarch64 marker (SETUP-02)."""
        data = tomli.loads(PYPROJECT_TOML.read_text())
        jetson_deps = data["project"]["optional-dependencies"]["jetson"]
        assert any(
            "Jetson.GPIO" in dep and "aarch64" in dep for dep in jetson_deps
        ), "Jetson.GPIO>=2.1.0; platform_machine=='aarch64' not found in jetson extra"
