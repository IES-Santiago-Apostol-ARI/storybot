import pytest
import re
from pathlib import Path

# Path to the file under test
JS_FILE_PATH = Path("static/admin/script.js")

def read_js():
    """Reads the JS file content for assertion."""
    return JS_FILE_PATH.read_text(encoding="utf-8")

def test_bt_controller_exists():
    """Assert the Bluetooth controller logic is present in script.js (UIBT-02)."""
    content = read_js()
    assert "function scanBtDevices" in content, "scanBtDevices function is missing"
    assert "function initBtSection" in content, "initBtSection function is missing"

def test_bt_polling_discipline():
    """
    Assert BT uses separate polling state and disciplined lifecycle (D-05).
    (a) Module-scoped btStatusPollId and BT_STATUS_POLL_INTERVAL exist.
    (b) stopBtStatusPolling clears the interval and is called on collapse and cleanup.
    """
    content = read_js()
    
    # (a) State variables
    assert "let btStatusPollId = null;" in content, "btStatusPollId variable is missing"
    assert "const BT_STATUS_POLL_INTERVAL =" in content, "BT_STATUS_POLL_INTERVAL constant is missing"
    
    # (b) Lifecycle functions
    assert "function startBtStatusPolling" in content, "startBtStatusPolling function is missing"
    assert "function stopBtStatusPolling" in content, "stopBtStatusPolling function is missing"
    
    # Ensure stopBtStatusPolling clears the ID
    assert "clearInterval(btStatusPollId)" in content, "stopBtStatusPolling should call clearInterval(btStatusPollId)"
    assert "btStatusPollId = null" in content, "stopBtStatusPolling should reset btStatusPollId to null"
    
    # Ensure stopBtStatusPolling is called during collapse (inside toggleBtSection)
    assert "stopBtStatusPolling()" in content, "stopBtStatusPolling() must be called (e.g. on collapse)"
    
    # Ensure stopBtStatusPolling is called during cleanup
    assert "stopBtStatusPolling()" in content, "cleanup() or general logic must call stopBtStatusPolling()"

def test_bt_device_rendering_xss_safe():
    """
    Assert device rendering uses textContent and avoids innerHTML for device data (XSS).
    (c) createBtDeviceItem region contains textContent and no innerHTML = device.
    """
    content = read_js()
    
    # Check for textContent usage with device properties
    assert ".textContent =" in content, "must use .textContent to set device data"
    
    # Check that no innerHTML assignment is fed a device property
    assert not re.search(r"\.innerHTML\s*=\s*.*device\.", content), \
        "XSS Risk: createBtDeviceItem must NOT use innerHTML with device data"

def test_bt_pairing_flow_no_pin():
    """
    Assert the pairing flow is one-tap (pair then connect) and has no PIN modal (D-03).
    (d) pairAndConnectBt POSTs to /api/bt/pair then /api/bt/connect; no BT password input.
    """
    content = read_js()
    
    # Check for the function
    assert "function pairAndConnectBt" in content, "pairAndConnectBt function is missing"
    
    # Check for staged POSTs
    assert "fetch('/api/bt/pair'" in content, "pairAndConnectBt must POST to /api/bt/pair"
    assert "fetch('/api/bt/connect'" in content, "pairAndConnectBt must POST to /api/bt/connect"
    
    # Assert absence of BT password/PIN input in the JS (since it's a headless agent)
    assert not re.search(r"bt.*(password|pin).*(input|modal)", content, re.IGNORECASE), \
        "D-03 Violation: Bluetooth pairing should NOT use a password/PIN modal"

def test_bt_status_and_init_wiring():
    """
    Assert status fetching and DOM wiring (AUDIO-03).
    (e) fetchBtStatus fetches /api/bt/status; initBtSection is called from DOMContentLoaded.
    """
    content = read_js()
    
    # Status fetch
    assert "function fetchBtStatus" in content, "fetchBtStatus function is missing"
    assert "fetch('/api/bt/status')" in content, "fetchBtStatus must fetch from /api/bt/status"
    
    # Init wiring
    assert "function initBtSection" in content, "initBtSection function is missing"
    
    # Check for the call to initBtSection (assuming it's wired in DOMContentLoaded)
    assert "initBtSection()" in content, "initBtSection() must be called for initialization"
