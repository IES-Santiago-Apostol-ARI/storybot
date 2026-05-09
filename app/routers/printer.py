"""POST /api/printer/print — sends a cover PNG to the Brother QL-820NWBc (D-18)."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.requests import Request
from pydantic import BaseModel, Field

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
