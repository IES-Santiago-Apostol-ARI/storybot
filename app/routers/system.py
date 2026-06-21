"""System status endpoints."""

import re
from typing import Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.dependencies import get_hardware, get_led_animator
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
    animator=Depends(get_led_animator),
) -> SystemStatus:
    """Rescan for hardware changes.

    Returns:
        Updated SystemStatus after rescan
    """
    status_dict = await hardware.rescan()
    # CR-02: rescan re-creates the "led" service, so re-point the sole-writer
    # engine at the freshly-probed driver; otherwise it would keep writing to the
    # orphaned old driver (split-brain / dual SPI owners).
    if animator is not None:
        animator.set_driver(hardware._services.get("led"))
    status_dict["platform"] = detect_platform()
    return SystemStatus(**status_dict)


@router.post("/led")
async def set_led_color(
    request: LEDRequest,
    animator=Depends(get_led_animator),
):
    """Set LED color via the animation engine (sole writer, D-11).

    Args:
        request: LED request with color (hex) and optional brightness
        animator: LedAnimator engine instance (None when not running)

    Returns:
        Status response with color and RGB values

    Raises:
        HTTPException: 503 if the LED engine is not running (D-12)
    """
    if animator is None:
        raise HTTPException(status_code=503, detail="LED engine not available")

    r, g, b = hex_to_rgb(request.color)
    # Apply brightness
    r = int(r * request.brightness)
    g = int(g * request.brightness)
    b = int(b * request.brightness)

    await animator.set_base(r, g, b)
    return {"status": "ok", "color": request.color, "rgb": [r, g, b]}


@router.post("/led/off")
async def turn_off_led(
    animator=Depends(get_led_animator),
):
    """Turn off LED via the animation engine (sole writer, D-11).

    Args:
        animator: LedAnimator engine instance (None when not running)

    Returns:
        Status response

    Raises:
        HTTPException: 503 if the LED engine is not running (D-12)
    """
    if animator is None:
        raise HTTPException(status_code=503, detail="LED engine not available")

    await animator.off()
    return {"status": "ok"}
