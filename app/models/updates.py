"""Update models for check, apply, and version operations."""

from typing import Optional

from pydantic import BaseModel, Field


class UpdateCheckResponse(BaseModel):
    """Response from checking for updates."""

    update_available: bool = Field(
        ..., description="Whether an update is available"
    )
    local_commit: str = Field(..., description="Local HEAD commit hash")
    remote_commit: str = Field(
        ..., description="Remote origin/main commit hash"
    )
    error: Optional[str] = Field(
        None, description="Error message if check failed"
    )


class UpdateVersionResponse(BaseModel):
    """Current version information."""

    version: str = Field(..., description="Git describe output")
    commit: str = Field(..., description="Short commit hash")
