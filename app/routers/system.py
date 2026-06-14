"""System status endpoints."""

import re
from typing import Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.dependencies import get_hardware
from app.models.system import SystemStatus
from app.services.hardware_manager import HardwareManager
from app.services.platform_detect import detect_platform


router = APIRouter()


class LEDRequest(BaseModel):
    """LED color control request."""

    color: str = Field(..., description="Hex color like #FF0000")
    brightness: float = Field(1.0, ge=0.0, le=1.0, description="Brightness multiplier (0.0-1.0)")

    @field_validator("color")
    @classmethod
    def validate_hex_color(cls, v: str) -> str:
        """Validate hex color format."""
        if not re.match(r"^#[0-9A-Fa-f]{6}$", v):
            raise ValueError("Invalid hex color format")
        return v


def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """Convert hex color to RGB tuple.

    Args:
        hex_color: Hex color string like "#FF0000"

    Returns:
        Tuple of (r, g, b) values (0-255 each)
    """
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


@router.get("/status", response_model=SystemStatus)
async def get_system_status(
    hardware: HardwareManager = Depends(get_hardware),
) -> SystemStatus:
    """Get system status including all hardware services.

    Returns:
        SystemStatus with hardware states, uptime, and version
    """
    status_dict = await hardware.get_status()
    status_dict["platform"] = detect_platform()
    return SystemStatus(**status_dict)


@router.post("/rescan", response_model=SystemStatus)
async def rescan_hardware(
    hardware: HardwareManager = Depends(get_hardware),
) -> SystemStatus:
    """Rescan for hardware changes.

    Returns:
        Updated SystemStatus after rescan
    """
    status_dict = await hardware.rescan()
    status_dict["platform"] = detect_platform()
    return SystemStatus(**status_dict)


@router.post("/led")
async def set_led_color(
    request: LEDRequest,
    hardware: HardwareManager = Depends(get_hardware),
):
    """Set LED color.

    Args:
        request: LED request with color (hex) and optional brightness
        hardware: Hardware manager instance

    Returns:
        Status response with color and RGB values

    Raises:
        HTTPException: If LED service is not available
    """
    led_service = hardware._services.get("led")
    if not led_service:
        raise HTTPException(status_code=503, detail="LED service not available")

    r, g, b = hex_to_rgb(request.color)
    # Apply brightness
    r = int(r * request.brightness)
    g = int(g * request.brightness)
    b = int(b * request.brightness)

    await led_service.set_color(r, g, b)
    return {"status": "ok", "color": request.color, "rgb": [r, g, b]}


@router.post("/led/off")
async def turn_off_led(
    hardware: HardwareManager = Depends(get_hardware),
):
    """Turn off LED.

    Args:
        hardware: Hardware manager instance

    Returns:
        Status response

    Raises:
        HTTPException: If LED service is not available
    """
    led_service = hardware._services.get("led")
    if not led_service:
        raise HTTPException(status_code=503, detail="LED service not available")

    await led_service.turn_off()
    return {"status": "ok"}
