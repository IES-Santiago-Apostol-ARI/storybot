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

    def test_load_returns_settings_from_file_when_exists(
        self, config_manager, temp_config_file
    ):
        """ConfigManager.load() returns Settings from file when config.json exists."""
        # Write config file
        config_data = {
            "led_brightness": 128,
            "audio_volume": 0.5,
            "tts_voice": "es_ES-glow_tenor",
        }
        temp_config_file.write_text(json.dumps(config_data))

        settings = config_manager.load()
        assert isinstance(settings, Settings)
        assert settings.led_brightness == 128
        assert settings.audio_volume == 0.5
        assert settings.tts_voice == "es_ES-glow_tenor"

    def test_default_tts_voice_matches_shipped_model(self, config_manager):
        """Default tts_voice is the voice download-models.sh installs (§1.7)."""
        settings = config_manager.load()
        assert settings.tts_voice == "es_ES-sharvard-medium"

    def test_save_writes_current_settings_to_file(
        self, config_manager, temp_config_file
    ):
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


class TestTTSSpeechDefaults:
    """Random speaker + child-friendly speaking rate (§4 follow-up)."""

    def test_default_tts_speaker_is_random(self):
        from app.config import Settings

        assert Settings().tts_speaker == "random"

    def test_default_tts_length_scale_slows_speech_for_children(self):
        from app.config import Settings

        assert Settings().tts_length_scale == 1.2


class TestTranscriptionSettings:
    """Whisper.cpp transcription of /admin audio uploads (PLAN.md Task 4)."""

    def test_transcription_enabled_by_default(self):
        from app.config import Settings

        assert Settings().transcription_enabled is True

    def test_default_whisper_bin_resolves_via_path(self):
        from app.config import Settings

        assert Settings().whisper_bin == "whisper-cli"

    def test_default_whisper_model_lives_under_models_dir(self):
        from app.config import Settings

        assert Settings().whisper_model == "models/whisper/ggml-small.bin"


class TestGetSettings:
    """IMPROVEMENTS.md 2.3: process-wide shared settings accessor."""

    def test_get_settings_returns_cached_instance(self):
        from app.config import get_settings

        assert get_settings() is get_settings()

    def test_get_settings_shares_the_config_manager_cache(self):
        from app.config import get_config_manager, get_settings

        assert get_settings() is get_config_manager().load()

    def test_invalidate_settings_rereads_config_file(self, tmp_path, monkeypatch):
        import json

        from app import config as config_mod

        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"led_brightness": 200}))
        monkeypatch.setattr(config_mod, "_manager", config_mod.ConfigManager(cfg))

        first = config_mod.get_settings()
        assert first.led_brightness == 200

        cfg.write_text(json.dumps({"led_brightness": 7}))
        # Still cached until invalidated
        assert config_mod.get_settings() is first

        config_mod.invalidate_settings()
        assert config_mod.get_settings().led_brightness == 7

    def test_manager_reload_propagates_to_get_settings(self, tmp_path, monkeypatch):
        """admin-style reload on the shared manager reaches get_settings()."""
        import json

        from app import config as config_mod

        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"led_brightness": 200}))
        monkeypatch.setattr(config_mod, "_manager", config_mod.ConfigManager(cfg))

        config_mod.get_settings()
        cfg.write_text(json.dumps({"led_brightness": 9}))
        config_mod.get_config_manager().reload()
        assert config_mod.get_settings().led_brightness == 9


class TestNoModuleSettingsSingletons:
    """IMPROVEMENTS.md 2.3: no module keeps a private import-time Settings copy."""

    SINGLETON_FREE_MODULES = [
        "app/routers/generate.py",
        "app/services/gpio_handler.py",
        "app/services/gpio_dispatcher.py",
        "app/services/system_control.py",
        "app/services/led_animator.py",
        "app/services/led_controller.py",
    ]

    def test_no_module_level_configmanager_load(self):
        from pathlib import Path

        for module in self.SINGLETON_FREE_MODULES:
            source = Path(module).read_text(encoding="utf-8")
            assert "ConfigManager().load()" not in source, (
                f"{module} still holds a module-level Settings copy -- "
                "use app.config.get_settings() instead"
            )

    def test_main_wires_app_state_to_shared_manager(self):
        from pathlib import Path

        source = Path("app/main.py").read_text(encoding="utf-8")
        assert "get_config_manager()" in source, (
            "app.state.config must be the shared manager so a reload() "
            "on it reaches every get_settings() caller"
        )
