"""Bluetooth management endpoints — scan, last speaker, status (Phase 26-03).

Read-only GET endpoints only this phase; pairing/connect POSTs are Phase 27.
Mirrors app/routers/wifi.py: per-request create_bt_manager() (no app.state
caching, RESEARCH Assumption A2) and pydantic response_model on scan/status.
"""

from fastapi import APIRouter

from app.models.bt import (
    BtConnectRequest,
    BtDevice,
    BtForgetText,
    BtPairRequest,
    BtStatus,
)
from app.services.bt_manager import create_bt_manager
from app.services.platform_detect import detect_platform

router = APIRouter(prefix="/api/bt", tags=["bt"])


@router.get("/scan", response_model=list[BtDevice])
async def scan_devices() -> list[dict]:
    """Scan for nearby Bluetooth audio devices (BT-01/BT-07, D-04/D-05/D-06).

    Returns a JSON list of ``{name, mac, rssi}`` entries — audio-only,
    RSSI-sorted strongest-first. No response_model on failure: the Mock
    backend returns a deterministic list instantly; the Real backend
    degrades to ``[]`` on any scan error (never 500s).
    """
    manager = create_bt_manager()
    return await manager.scan()


@router.get("/last")
async def get_last_speaker() -> dict | None:
    """Return the remembered last-connected speaker (BT-06, D-11).

    No response_model: ``null`` is a valid response when nothing is paired
    yet, and pydantic response_models forbid None unless explicitly typed.
    Returns ``{name, mac, last_connected}`` or ``null``.
    """
    manager = create_bt_manager()
    return await manager.get_last_speaker()


@router.get("/status", response_model=BtStatus)
async def get_status() -> dict:
    """Return current Bluetooth service status (BT-06 informational).

    Composes the manager's get_status() dict with detect_platform() and an
    adapter-presence check into a BtStatus response. Under TESTING the
    factory returns MockBtManager → is_mock=true.
    """
    manager = create_bt_manager()
    base = await manager.get_status()
    from app.services.bt_manager import _bt_adapter_present

    return {
        "name": base.get("name", "bt"),
        "is_mock": manager.is_mock,
        "status": base.get("status", "ok"),
        "platform": detect_platform(),
        "adapter_present": _bt_adapter_present(),
        "error_message": base.get("error_message"),
        "connected_mac": base.get("connected_mac"),
        "sink": base.get("sink", "wired"),
    }


@router.post("/pair")
async def pair_speaker(body: BtPairRequest) -> dict:
    """Pair a new Bluetooth speaker (BT-02).

    Delegates to the per-request manager's ``pair(mac, name)``; the bt
    manager already returns the ``{ok: ...}`` shape directly (unlike wifi
    where the router wraps it), so it is returned unchanged. A malformed
    MAC never reaches this handler: the pydantic ``_MAC`` pattern on
    ``BtPairRequest`` yields HTTP 422 first (Pitfall 5, T-27-01).
    """
    return await create_bt_manager().pair(body.mac, body.name)


@router.post("/connect")
async def connect_speaker(body: BtConnectRequest) -> dict:
    """Connect a previously paired speaker (BT-04)."""
    return await create_bt_manager().connect(body.mac)


@router.post("/disconnect")
async def disconnect_speaker(body: BtConnectRequest | None = None) -> dict:
    """Disconnect the current speaker and fall back to wired (BT-05)."""
    return await create_bt_manager().disconnect(body.mac if body else None)


@router.post("/forget")
async def forget_speaker(body: BtForgetText) -> dict:
    """Forget a paired speaker (BT-03)."""
    return await create_bt_manager().forget(body.mac)
