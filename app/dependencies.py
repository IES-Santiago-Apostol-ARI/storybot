"""FastAPI dependencies."""

from fastapi import Request

from app.services.hardware_manager import HardwareManager
from app.services.story_manager import StoryManager
from app.config import ConfigManager


async def get_hardware(request: Request) -> HardwareManager:
    """Get hardware manager from app state.

    Args:
        request: FastAPI request

    Returns:
        HardwareManager instance
    """
    return request.app.state.hardware


async def get_config(request: Request) -> ConfigManager:
    """Get config manager from app state.

    Args:
        request: FastAPI request

    Returns:
        ConfigManager instance
    """
    return request.app.state.config


async def get_story_manager(request: Request) -> StoryManager:
    """Get story manager from app state.

    Args:
        request: FastAPI request

    Returns:
        StoryManager instance
    """
    return request.app.state.story_manager


async def get_led_animator(request: Request):
    """Get the LedAnimator engine from app state.

    Mirrors ``get_hardware`` style. Returns ``None`` when the animator failed to
    initialize or is absent (D-12: the route decides 503 on ``None``).

    Args:
        request: FastAPI request

    Returns:
        LedAnimator instance, or None when unavailable.
    """
    return getattr(request.app.state, "led_animator", None)
