"""Bluetooth models for scan, status, and paired-speaker memory."""

from pydantic import BaseModel, Field


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


class LastSpeaker(BaseModel):
    """The remembered last-connected speaker (BT-06, N=1)."""

    name: str = Field(..., description="Speaker display name")
    mac: str = Field(..., description="Speaker MAC address")
    last_connected: str = Field(
        ..., description="ISO-8601 timestamp of the last connection"
    )
