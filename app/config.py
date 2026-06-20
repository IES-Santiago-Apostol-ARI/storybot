"""Configuration management."""

import json
from pathlib import Path

from pydantic import BaseModel


class Settings(BaseModel):
    """Application settings."""

    led_brightness: int = 255
    led_count: int = 21  # D-10: wired strip length (within 8–30 spec)
    led_max_brightness: float = (
        0.30  # D-09: ~75/255 child-safe baseline (cap applied before gamma)
    )
    led_spi_bus: int = (
        0  # D-12: spidev0.0 default; node confirmed after jetson-io in Phase 34
    )
    led_spi_dev: int = 0  # D-12
    led_spi_speed_hz: int = 6_400_000  # D-11: Option A, 8 SPI bits per WS bit
    led_color_order: str = "GRB"  # D-13: WS2812B standard
    led_gamma: float = (
        2.2  # sRGB approx; deterministic LUT (see app.services.led_spi._gamma_lut)
    )
    audio_volume: float = 1.0
    tts_voice: str = "es_ES-glow_tenor"
    nfc_reader_device: str = "usb:072f:2200"
    printer_model: str = "QL-800"

    class Config:
        json_encoders = {Path: str}
        validate_default = True


class ConfigManager:
    """Manage application configuration."""

    def __init__(self, config_path: Path | str | None = None) -> None:
        """Initialize config manager.

        Args:
            config_path: Path to config.json file. Defaults to content/config.json
        """
        if config_path is None:
            # Default to content/config.json relative to project root
            project_root = Path(__file__).parent.parent
            config_path = project_root / "content" / "config.json"
        self.config_path = Path(config_path)
        self._settings: Settings | None = None

    def load(self) -> Settings:
        """Load settings from config file.

        Returns:
            Settings object with defaults or loaded values
        """
        if self._settings is not None:
            return self._settings

        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text())
                self._settings = Settings(**data)
            except (json.JSONDecodeError, TypeError):
                # If config is invalid, use defaults
                self._settings = Settings()
        else:
            self._settings = Settings()

        return self._settings

    def save(self, settings: Settings) -> None:
        """Save settings to config file.

        Args:
            settings: Settings to save
        """
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(settings.model_dump_json(indent=2))
        self._settings = settings

    def reload(self) -> Settings:
        """Reload settings from config file.

        Returns:
            Reloaded Settings object
        """
        self._settings = None
        return self.load()
