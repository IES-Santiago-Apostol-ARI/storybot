"""Capability profile endpoint (API-01)."""

from fastapi import APIRouter, Request

from app.models.capability import CapabilityProfile

router = APIRouter(prefix="/api", tags=["capabilities"])


@router.get("/capabilities", response_model=CapabilityProfile)
async def get_capabilities(request: Request) -> CapabilityProfile:
    """Return the live device capability profile (API-01)."""
    return request.app.state.capability
