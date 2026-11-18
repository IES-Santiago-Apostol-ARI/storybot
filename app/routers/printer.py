"""POST /api/printer/print — sends a cover PNG to the Brother QL-820NWBc (D-18)."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.requests import Request
from pydantic import BaseModel, Field

from app.config import get_config_manager, get_settings
from app.models.bt import _MAC, BtDevice
from app.services.bt_manager import create_bt_manager

router = APIRouter(prefix="/api/printer", tags=["printer"])

# T-16-02: only files under these roots may be printed.
_ALLOWED_ROOTS = (Path("content/generated"), Path("content/stories"))


class PrintRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=512)


def _validate_print_path(raw: str) -> Path:
    """Resolve raw path and assert it lives under an allowed root."""
    if ".." in Path(raw).parts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="path traversal rejected",
        )
    candidate = Path(raw).resolve()
    cwd = Path.cwd().resolve()
    ok = False
    for root in _ALLOWED_ROOTS:
        root_resolved = (cwd / root).resolve()
        if hasattr(candidate, "is_relative_to"):
            if candidate.is_relative_to(root_resolved):
                ok = True
                break
        else:
            try:
                candidate.relative_to(root_resolved)
                ok = True
                break
            except ValueError:
                pass
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="path must be under content/generated/ or content/stories/",
        )
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="file not found",
        )
    return candidate


@router.post("/print")
async def print_sticker(body: PrintRequest, request: Request) -> dict:
    target = _validate_print_path(body.path)

    printer = getattr(request.app.state, "printer", None)
    if printer is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="printer service not registered",
        )
    try:
        await printer.print_sticker(target)
    except Exception as e:
        import json
        import sys

        print(
            json.dumps(
                {
                    "event": "print_failed",
                    "path": str(target),
                    "reason": type(e).__name__,
                }
            ),
            file=sys.stderr,
        )
        return {"ok": False, "error": type(e).__name__}
    return {"ok": True}


class PrinterDeviceRequest(BaseModel):
    mac: str = Field(..., pattern=_MAC)
    name: str = Field("", max_length=64)


@router.get("/scan", response_model=list[BtDevice])
async def scan_printers() -> list[dict]:
    """Discover nearby QL-820NWB printers (~15 s blocking scan)."""
    return await create_bt_manager().scan_printers()


@router.get("/device")
async def get_printer_device() -> dict:
    """The Bluetooth printer covers are sent to."""
    settings = get_settings()
    return {"name": settings.printer_bt_name, "mac": settings.printer_bt_address}


@router.put("/device")
async def set_printer_device(body: PrinterDeviceRequest) -> dict:
    """Use another printer unit. No pairing needed: BlueZ pairs on the first
    RFCOMM connect (no PIN), so the address is all the print path needs."""
    settings = get_settings().model_copy(
        update={"printer_bt_address": body.mac.upper(), "printer_bt_name": body.name}
    )
    get_config_manager().save(settings)
    return {"ok": True}
