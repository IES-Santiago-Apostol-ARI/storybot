"""WiFi management endpoints — scan, connect, disconnect, status."""

import json
import sys

from fastapi import APIRouter

from app.models.wifi import WifiConnectRequest, WifiNetwork, WifiStatus
from app.services.wifi_manager import create_wifi_manager

router = APIRouter(prefix="/api/wifi", tags=["wifi"])


@router.get("/scan", response_model=list[WifiNetwork])
async def scan_networks() -> list[dict]:
    """Scan for visible WiFi networks.

    Returns list of networks with ssid, signal, security, connected fields.
    """
    manager = create_wifi_manager()
    return await manager.scan()


@router.post("/connect")
async def connect_network(body: WifiConnectRequest) -> dict:
    """Connect to a WiFi network.

    Accepts SSID and password, returns ok:true on success,
    ok:false with error detail on failure.
    """
    manager = create_wifi_manager()
    try:
        success = await manager.connect(body.ssid, body.password)
        if success:
            return {"ok": True}
        return {"ok": False, "error": "connection_failed"}
    except Exception as e:
        print(
            json.dumps(
                {
                    "event": "wifi_connect_failed",
                    "ssid": body.ssid,
                    "reason": type(e).__name__,
                }
            ),
            file=sys.stderr,
        )
        return {"ok": False, "error": type(e).__name__}


@router.post("/disconnect")
async def disconnect_network() -> dict:
    """Disconnect from current WiFi network.

    Returns ok:true on success, ok:false if not connected.
    """
    manager = create_wifi_manager()
    success = await manager.disconnect()
    if success:
        return {"ok": True}
    return {"ok": False, "error": "not_connected"}


@router.get("/status", response_model=WifiStatus)
async def get_status() -> dict:
    """Get current WiFi connection status.

    Returns state, ssid (or null), and interface name.
    """
    manager = create_wifi_manager()
    return await manager.status()
