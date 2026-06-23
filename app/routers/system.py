"""System status endpoints."""

import re
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.dependencies import get_hardware, get_led_animator, get_story_manager
from app.models.system import SystemStatus
from app.services.hardware_manager import HardwareManager
from app.services.led_animator import Mode
from app.services.platform_detect import detect_platform
from app.services.story_manager import StoryManager

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


class LEDState(str, Enum):
    """Semantic LED playback-lifecycle states (D-02).

    Str-based Enum so Pydantic validates the request ``state`` against the
    exact member set and rejects unknown values with 422 automatically
    (ASVS V5 default-deny — T-33-06 mitigation). There is NO per-frame
    brightness field on this route (D-02 shape locked), so the endpoint
    cannot be abused to re-create a second writer.
    """

    PLAYBACK = "playback"
    PAUSE = "pause"
    RESUME = "resume"
    IDLE = "idle"
    ENDED = "ended"
    THINKING = "thinking"


class LEDStateRequest(BaseModel):
    """Semantic LED state request (D-02 additive endpoint).

    The client sends a semantic state + a story identifier; the backend
    resolves ``led_color`` via ``story_manager`` (D-03) and drives the
    engine. There is no color/brightness field here on purpose.
    """

    state: LEDState
    story_id: str | None = None
    nfc_uid: str | None = None


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
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


@router.post("/led/state")
async def set_led_state(
    http_request: Request,
    request: LEDStateRequest,
    animator=Depends(get_led_animator),
    story_manager: StoryManager = Depends(get_story_manager),
):
    """Drive the LED engine into a semantic playback-lifecycle state (D-02).

    Additive — does NOT overload :http:post:`/api/system/led` (D-02 / Phase 32
    sole-writer rule). The route is the SOLE writer's driver: it resolves the
    story ``led_color`` backend-side via ``story_manager`` (D-03) and calls the
    engine's concrete API. The engine is the only thing that writes the strip.

    State mapping (D-12 authoritative pause mechanism — ``pause`` is a ``_paused``
    flag on PLAYBACK, NOT a separate ``Mode``)::

        playback -> animator.set_mode(Mode.PLAYBACK, color=rgb)
        pause    -> animator.pause()       (freeze breath; do NOT set_mode)
        resume   -> animator.resume()      (re-anchor _phase0; do NOT set_mode)
        idle     -> animator.set_mode(Mode.IDLE)
        ended    -> animator.set_mode(Mode.IDLE)  (cross-fades to idle, LED-22)
        thinking -> animator.set_mode(Mode.THINKING)

    Args:
        request: ``LEDStateRequest`` — validated semantic state + optional
            story identifier (``nfc_uid`` takes precedence over ``story_id``).
        animator: LedAnimator engine instance (None when not running).
        story_manager: StoryManager used to resolve ``led_color`` (D-03).

    Returns:
        ``{"status": "ok", "state": <state>, "rgb": [r,g,b] | null}`` — the
        resolved RGB is included only when a story identifier resolved a color.

    Raises:
        HTTPException: 503 if the LED engine is not running (mirrors /led).
    """
    # T-33-08: never assume the engine exists; mirror the /led 503-on-None.
    if animator is None:
        raise HTTPException(status_code=503, detail="LED engine not available")

    # D-03: resolve the story's led_color backend-side. NFC uid takes
    # precedence; fall back to story_id; None when neither resolves (the
    # engine falls back gracefully — T-33-07 accept disposition).
    rgb: tuple[int, int, int] | None = None
    story = None
    if request.nfc_uid:
        story = story_manager.get_story_by_nfc(request.nfc_uid)
    elif request.story_id:
        story = story_manager.get_story(request.story_id)
    if story is not None and getattr(story, "led_color", None):
        rgb = hex_to_rgb(story.led_color)

    state = request.state

    # BTN-03: track current_story_id on the GpioDispatcher so the image
    # button handler knows which story to generate a cover for. NFC uid
    # takes precedence (resolves via story_manager), then story_id.
    dispatcher = getattr(http_request.app.state, "gpio_dispatcher", None)
    if state == LEDState.PLAYBACK and dispatcher is not None:
        # Resolve the definitive story ID from nfc_uid or story_id
        resolved_story_id: str | None = None
        if request.nfc_uid:
            resolved_story = story_manager.get_story_by_nfc(request.nfc_uid)
            if resolved_story is not None:
                resolved_story_id = getattr(resolved_story, "id", None)
        elif request.story_id:
            resolved_story_id = request.story_id
        dispatcher.current_story_id = resolved_story_id
    elif state in (LEDState.IDLE, LEDState.ENDED) and dispatcher is not None:
        dispatcher.current_story_id = None

    if state == LEDState.PLAYBACK:
        # D-13: PLAYBACK is a base mode; pass the resolved color so the
        # breathing effect renders in the story color. None is acceptable —
        # the engine keeps the last mode_color.
        animator.set_mode(Mode.PLAYBACK, color=rgb)
    elif state == LEDState.PAUSE:
        # D-12: authoritative pause — freeze the breath via the _paused flag,
        # NOT a set_mode call.
        animator.pause()
    elif state == LEDState.RESUME:
        # D-12: resume re-anchors _phase0 so the breath continues smoothly.
        animator.resume()
    elif state == LEDState.IDLE:
        animator.set_mode(Mode.IDLE)
    elif state == LEDState.ENDED:
        # LED-12 / D-12: ended cross-fades to idle (Mode.IDLE renders the
        # configured idle glow).
        animator.set_mode(Mode.IDLE)
    elif state == LEDState.THINKING:
        animator.set_mode(Mode.THINKING)

    return {"status": "ok", "state": state.value, "rgb": list(rgb) if rgb else None}


@router.post("/poweroff")
async def poweroff_system():
    """Initiate system poweroff.

    Starts the configured poweroff command as a detached subprocess so the
    FastAPI event loop is not blocked. Returns immediately with status ok.

    Returns:
        Status response confirming the poweroff command was initiated.
    """
    from app.services.system_control import poweroff

    await poweroff()
    return {"status": "ok"}
