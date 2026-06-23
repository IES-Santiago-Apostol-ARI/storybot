"""System models for API responses."""


from pydantic import BaseModel, Field


class HardwareState(BaseModel):
    """State of a hardware service."""

    name: str = Field(..., description="Service name")
    is_mock: bool = Field(..., description="True if using mock implementation")
    status: str = Field(..., description="Service status: ok, error, or not_connected")
    error_message: str | None = Field(
        None, description="Error message if status is error"
    )


class SystemStatus(BaseModel):
    """Overall system status."""

    hardware: dict[str, HardwareState] = Field(
        ..., description="Hardware service states"
    )
    uptime_seconds: float = Field(..., description="Server uptime in seconds")
    version: str = Field(..., description="StoryBot version")
    platform: str | None = Field(
        None,
        description="Detected hardware platform: jetson|rpi|generic (informational)",
    )
