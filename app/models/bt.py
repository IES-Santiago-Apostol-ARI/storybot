"""Bluetooth models for scan, status, and paired-speaker memory."""

from pydantic import BaseModel, Field

# Strict MAC regex — the V5 input-validation control for the whole phase. The MAC is
# the ONLY safe source for D-Bus object paths and pactl card/sink names downstream
# (T-27-01): a regex-validated MAC can never break out into a path or a shell arg.
_MAC = r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$"


class BtDevice(BaseModel):
    """A discovered Bluetooth audio device from a scan.

    RSSI is signal strength in negative dBm; do NOT constrain with ge=0.
    """

    name: str = Field(..., description="Device display name (Alias/Name)")
    mac: str = Field(..., description="Device MAC address (BT-01)")
    rssi: int | None = Field(
        None,
        description="Signal strength in negative dBm; None if unavailable (BT-07)",
    )


class BtStatus(BaseModel):
    """Current Bluetooth service status (mirrors WifiStatus shape)."""

    name: str = Field(..., description="Service name")
    is_mock: bool = Field(..., description="True when running the Mock backend")
    status: str = Field(..., description="Service status slug (e.g. ok/unavailable)")
    platform: str = Field(..., description="Detected platform: jetson|rpi|generic")
    adapter_present: bool = Field(
        ..., description="True when a BT adapter (hci*) is present"
    )
    error_message: str | None = Field(
        None, description="Optional error detail; None when status is ok"
    )
    connected_mac: str | None = Field(
        None,
        description="MAC of the currently connected speaker; None when none",
    )
    sink: str = Field(
        ..., description="Current default audio sink: 'wired' or the BT sink name"
    )


class LastSpeaker(BaseModel):
    """The remembered last-connected speaker (BT-06, N=1)."""

    name: str = Field(..., description="Speaker display name")
    mac: str = Field(..., description="Speaker MAC address")
    last_connected: str = Field(
        ..., description="ISO-8601 timestamp of the last connection"
    )


class BtPairRequest(BaseModel):
    """Request body for pairing a new speaker (BT-02)."""

    mac: str = Field(..., pattern=_MAC, description="Speaker MAC to pair")
    name: str | None = Field(None, description="Optional friendly name for the speaker")


class BtConnectRequest(BaseModel):
    """Request body for connecting a previously paired speaker (BT-03)."""

    mac: str = Field(..., pattern=_MAC, description="Speaker MAC to connect")


class BtForgetText(BaseModel):
    """Request body for forgetting a paired speaker (BT-04)."""

    mac: str = Field(..., pattern=_MAC, description="Speaker MAC to forget")
