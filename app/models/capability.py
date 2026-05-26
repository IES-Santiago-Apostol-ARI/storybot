"""Capability profile model for v1.3 device self-awareness (CAP-01..04)."""

from pydantic import BaseModel, Field


class CapabilityProfile(BaseModel):
    """Device AI capability profile, produced at startup by probe_capability()."""

    ai_enabled: bool = Field(
        ..., description="Master AI gate — CAP-03: stored on app.state.ai_enabled"
    )
    tts_available: bool = Field(
        ...,
        description="TTS available — equals ai_enabled in v1.3 per D-08",
    )
    cover_gen: bool = Field(
        ...,
        description=(
            "Cover image generation available — " "equals ai_enabled in v1.3 per D-08"
        ),
    )
    printer: bool = Field(
        ...,
        description="Printer available — independent of ai_enabled per D-08",
    )
    reason: str = Field(
        ...,
        description=(
            "Short slug from D-05 enum "
            "(e.g. auto-detect:cuda+ram-ok, env-override:forced-on)"
        ),
    )
