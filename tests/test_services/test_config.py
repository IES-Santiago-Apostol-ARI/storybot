"""Tests for configuration management."""
import json

import pytest

from app.config import ConfigManager, Settings


@pytest.fixture
def temp_config_file(tmp_path):
    """Create a temporary config file."""
    return tmp_path / "config.json"


@pytest.fixture
def config_manager(temp_config_file):
    """Create a ConfigManager instance with temp file."""
    return ConfigManager(config_path=temp_config_file)


class TestConfigManager:
    """Test ConfigManager functionality."""

    def test_load_returns_default_settings_when_config_missing(self, config_manager):
        """ConfigManager.load() returns Settings with defaults when config.json missing."""
        settings = config_manager.load()
        assert isinstance(settings, Settings)
        assert settings.led_brightness == 255
        assert settings.audio_volume == 1.0

    def test_load_returns_settings_from_file_when_exists(self, config_manager, temp_config_file):
        """ConfigManager.load() returns Settings from file when config.json exists."""
        # Write config file
        config_data = {
            "led_brightness": 128,
            "audio_volume": 0.5,
            "tts_voice": "es_ES-glow_tenor"
        }
        temp_config_file.write_text(json.dumps(config_data))

        settings = config_manager.load()
        assert isinstance(settings, Settings)
        assert settings.led_brightness == 128
        assert settings.audio_volume == 0.5
        assert settings.tts_voice == "es_ES-glow_tenor"

    def test_save_writes_current_settings_to_file(self, config_manager, temp_config_file):
        """ConfigManager.save() writes current settings to config.json."""
        settings = Settings(led_brightness=200, audio_volume=0.8)
        config_manager.save(settings)

        assert temp_config_file.exists()
        data = json.loads(temp_config_file.read_text())
        assert data["led_brightness"] == 200
        assert data["audio_volume"] == 0.8

    def test_reload_re_reads_config_file(self, config_manager, temp_config_file):
        """ConfigManager.reload() re-reads file and updates settings."""
        # Initial load with defaults
        initial_settings = config_manager.load()
        assert initial_settings.led_brightness == 255

        # Write new config
        temp_config_file.write_text(json.dumps({"led_brightness": 100}))

        # Reload and verify
        reloaded_settings = config_manager.reload()
        assert reloaded_settings.led_brightness == 100
