"""Pydantic models for /api/generated routes."""

from pydantic import BaseModel, Field


class PromoteRequest(BaseModel):
    """Request body for promoting a generated story to curated."""

    title: str = Field(..., min_length=1, max_length=200)
    emoji: str = Field(..., min_length=1, max_length=8)
    led_color: str = Field(..., min_length=1, max_length=32)
