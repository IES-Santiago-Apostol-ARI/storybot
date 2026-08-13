"""Configuration management."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator

from app.services.atomic_io import write_json_atomic


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
    led_spi_speed_hz: int = (
        6_400_000  # D-11 / LED-26: Option A, 8 SPI bits per WS bit.
        # On-device tuning: if Option A fails to render cleanly on the real strip,
        # try Option B (4 SPI bits/WS bit) by halving to 3_200_000 and testing.
        # See deploy/led-uat-checklist.md for validation steps.
    )
    led_color_order: str = "GRB"  # D-13: WS2812B standard
    led_gamma: float = (
        2.2  # sRGB approx; deterministic LUT (see app.services.led_spi._gamma_lut)
    )
    # Effect tunables (Phase 33)
    led_breathe_period_s: float = 4.5  # D-06: ~4-5 s slow calm breath
    led_breathe_trough: float = 0.35  # D-06: dip to ~30-40%, never off
    led_comet_period_s: float = 2.0  # D-08: one full loop
    led_comet_tail: int = 3  # D-08: short fading tail
    led_idle_color: str = "#1A0F00"  # D-07: warm dim amber idle glow
    led_error_color: str = "#FF6A00"  # D-09: amber error indication (never red, B~0)
    led_accum_color: str = "#FFFFFF"  # D-20: neutral parameter-accumulation color
    led_boot_wipe_s: float = 1.0  # D-10: boot wipe duration
    led_crossfade_s: float = 0.5  # D-17: default cross-fade duration
    audio_volume: float = 1.0
    tts_voice: str = "es_ES-sharvard-medium"
    # Speaker choice for multi-speaker voices (sharvard: M=0, F=1).
    # "random" picks one per story so children don't know who narrates.
    tts_speaker: str = "random"  # "random" | "M" | "F"
    # Piper phoneme-duration multiplier; >1 = slower. 1.2 ≈ 20% slower —
    # the default rate is too fast for ages 3-6.
    tts_length_scale: float = 1.2
    # Story speaking-speed multiplier on top of tts_length_scale;
    # 1.0 = current speed, >1 faster, <1 slower. Clamped to [0.5, 2.0].
    tts_speed: float = 1.0
    # Max upload sizes (MB). Clamped to sane ranges so a bad config.json
    # value cannot disable protection or starve the SD card.
    max_audio_upload_mb: int = 50
    max_cover_upload_mb: int = 5
    # Whisper.cpp transcription of /admin audio uploads. Effective only when
    # the binary, model and ffmpeg exist on disk — dev machines without them
    # silently skip transcription (uploads still succeed).
    transcription_enabled: bool = True
    whisper_bin: str = "whisper-cli"  # bare name resolves via PATH
    whisper_model: str = "models/whisper/ggml-small.bin"
    nfc_reader_device: str = "usb:072f:2200"
    printer_model: str = "QL-800"
    # GPIO button pin mapping (Jetson.GPIO BOARD mode = physical J2 pin)
    gpio_power_pin: int = 7
    gpio_interrupt_pin: int = 15
    gpio_image_pin: int = 29
    gpio_animation_pin: int = 31
    gpio_bounce_ms: int = 200
    # --- Phase 35 GPIO (D-11) ---
    gpio_debounce_ms: int = 50
    gpio_poll_interval_s: float = 0.02
    poweroff_cmd: list[str] = ["/usr/bin/sudo", "/sbin/poweroff"]
    gpio_enabled: bool = True

    # json_encoders was dropped in the ConfigDict migration: no field is
    # Path-typed and save() serializes via model_dump_json.
    model_config = ConfigDict(validate_default=True)

    @field_validator("tts_speed")
    @classmethod
    def _clamp_tts_speed(cls, v: float) -> float:
        # Clamp instead of raising: a bad config.json value must not crash
        # the app at startup (matches the load()-falls-back-to-defaults ethos).
        return min(max(v, 0.5), 2.0)

    @field_validator("max_audio_upload_mb")
    @classmethod
    def _clamp_max_audio_upload_mb(cls, v: int) -> int:
        return min(max(v, 1), 500)

    @field_validator("max_cover_upload_mb")
    @classmethod
    def _clamp_max_cover_upload_mb(cls, v: int) -> int:
        return min(max(v, 1), 100)


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
        write_json_atomic(self.config_path, settings.model_dump(), indent=2)
        self._settings = settings

    def reload(self) -> Settings:
        """Reload settings from config file.

        Returns:
            Reloaded Settings object
        """
        self._settings = None
        return self.load()


# Process-wide shared manager (IMPROVEMENTS.md 2.3). Modules must NOT keep
# private module-level `ConfigManager().load()` copies — those are frozen at
# import and a reload() on app.state.config never reaches them. Call
# get_settings() at use time instead; app.state.config is this same manager,
# so reload()/save() on it propagates everywhere.
_manager = ConfigManager()


def get_config_manager() -> ConfigManager:
    """Return the process-wide shared ConfigManager."""
    return _manager


def get_settings() -> Settings:
    """Return the process-wide cached Settings (cheap: cached after first read)."""
    return _manager.load()


def invalidate_settings() -> None:
    """Drop the cached Settings; the next get_settings() re-reads config.json."""
    _manager.reload()
