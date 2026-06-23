"""WiFi models for scan, connect, and status operations."""


from pydantic import BaseModel, Field


class WifiNetwork(BaseModel):
    """A visible WiFi network from scan results."""

    ssid: str = Field(..., description="Network name")
    signal: int = Field(..., ge=0, le=100, description="Signal strength 0-100")
    security: str = Field(..., description="Security type: open, WPA2, WPA3, etc.")
    connected: bool = Field(False, description="Whether device is connected to this network")


class WifiConnectRequest(BaseModel):
    """Request to connect to a WiFi network."""

    ssid: str = Field(..., min_length=1, description="Network SSID")
    password: str = Field(..., min_length=8, description="WPA2 password (8+ chars)")


class WifiStatus(BaseModel):
    """Current WiFi connection status."""

    state: str = Field(..., description="connected or disconnected")
    ssid: str | None = Field(None, description="Connected network SSID")
    interface: str = Field(..., description="WiFi interface name")
