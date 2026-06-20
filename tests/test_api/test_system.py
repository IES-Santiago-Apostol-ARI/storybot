"""Tests for system API endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(monkeypatch):
    """Create test client with lifespan context.

    Force AI enabled so TTS is loaded and hardware status includes it.
    """
    monkeypatch.setenv("STORYBOT_AI", "1")
    with TestClient(app) as c:
        yield c


class TestSystemEndpoints:
    """Test system endpoint functionality."""

    def test_root_returns_ok(self, client):
        """GET / redirects to children's kiosk interface."""
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 307  # Temporary redirect
        assert response.headers["location"] == "/children/"

    def test_system_status_returns_hardware_state(self, client):
        """GET /api/system/status returns SystemStatus."""
        response = client.get("/api/system/status")
        assert response.status_code == 200
        data = response.json()
        assert "hardware" in data
        assert "uptime_seconds" in data
        assert "version" in data
        assert data["version"] == "0.1.0"

        # Verify all 4 services are present
        hardware = data["hardware"]
        assert "tts" in hardware
        assert "nfc" in hardware
        assert "led" in hardware
        assert "audio" in hardware

        # Verify each service has is_mock flag
        for service_name, service_state in hardware.items():
            assert "is_mock" in service_state
            assert "status" in service_state
            assert service_state["name"] == service_name

    def test_system_rescan_triggers_detection(self, client):
        """POST /api/system/rescan returns updated status."""
        response = client.post("/api/system/rescan")
        assert response.status_code == 200
        data = response.json()
        assert "hardware" in data
        assert "uptime_seconds" in data
        assert "version" in data

        # Verify all 4 services after rescan
        hardware = data["hardware"]
        assert "tts" in hardware
        assert "nfc" in hardware
        assert "led" in hardware
        assert "audio" in hardware


class TestLEDEndpoints:
    """Test LED control endpoints."""

    def test_set_led_color_with_valid_hex(self, client):
        """POST /api/system/led with valid hex color returns success."""
        response = client.post("/api/system/led", json={"color": "#FF0000"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["color"] == "#FF0000"
        assert "rgb" in data
        assert data["rgb"] == [255, 0, 0]

    def test_set_led_color_with_brightness(self, client):
        """POST /api/system/led with brightness applies brightness multiplier."""
        response = client.post(
            "/api/system/led", json={"color": "#FF0000", "brightness": 0.5}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["color"] == "#FF0000"
        assert data["rgb"] == [127, 0, 0]  # 255 * 0.5 = 127

    def test_set_led_color_with_invalid_hex_format(self, client):
        """POST /api/system/led with invalid hex format returns 422."""
        response = client.post("/api/system/led", json={"color": "FF0000"})  # Missing #
        assert response.status_code == 422

    def test_set_led_color_with_invalid_hex_values(self, client):
        """POST /api/system/led with invalid hex values returns 422."""
        response = client.post(
            "/api/system/led", json={"color": "#GGGGGG"}  # Invalid hex chars
        )
        assert response.status_code == 422

    def test_set_led_color_with_invalid_hex_length(self, client):
        """POST /api/system/led with invalid hex length returns 422."""
        response = client.post("/api/system/led", json={"color": "#FFF"})  # Too short
        assert response.status_code == 422

    def test_set_led_color_with_invalid_brightness(self, client):
        """POST /api/system/led with brightness > 1.0 returns 422."""
        response = client.post(
            "/api/system/led", json={"color": "#FF0000", "brightness": 1.5}
        )
        assert response.status_code == 422

    def test_turn_off_led(self, client):
        """POST /api/system/led/off turns off LED."""
        # First set a color
        client.post("/api/system/led", json={"color": "#FF0000"})

        # Then turn off
        response = client.post("/api/system/led/off")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_various_hex_colors(self, client):
        """POST /api/system/led converts various hex colors correctly."""
        test_cases = [
            ("#00FF00", [0, 255, 0]),
            ("#0000FF", [0, 0, 255]),
            ("#FFFFFF", [255, 255, 255]),
            ("#000000", [0, 0, 0]),
            ("#FF00FF", [255, 0, 255]),
        ]

        for hex_color, expected_rgb in test_cases:
            response = client.post("/api/system/led", json={"color": hex_color})
            assert response.status_code == 200
            data = response.json()
            assert data["rgb"] == expected_rgb

    @pytest.mark.xfail(strict=False, reason="engine wiring lands in 32-03")
    def test_led_routes_through_engine_not_service(self, client):
        """
        LED-06: Verify /api/system/led routes through the animator, not the driver.
        Selector: -k routes_through_engine
        """
        from unittest.mock import MagicMock
        
        # Spy on animator and service
        animator = app.state.led_animator
        service = animator._led_service if hasattr(animator, "_led_service") else None
        
        if animator is None or service is None:
            pytest.fail("Animator or service missing from state")

        animator.set_base = MagicMock(side_effect=animator.set_base)
        service.set_color = MagicMock(side_effect=service.set_color)

        client.post("/api/system/led", json={"color": "#FF0000"})

        # Assert animator was called, but driver was NOT called directly by the route
        assert animator.set_base.called
        assert not service.set_color.called

    @pytest.mark.xfail(strict=False, reason="engine wiring lands in 32-03")
    def test_led_returns_503_when_animator_missing(self, client, monkeypatch):
        """
        LED-09: Verify /api/system/led returns 503 when animator is not initialized.
        Selector: -k animator_missing
        """
        # Temporarily remove animator from state
        monkeypatch.setattr(app.state, "led_animator", None)
        
        response = client.post("/api/system/led", json={"color": "#FF0000"})
        assert response.status_code == 503
