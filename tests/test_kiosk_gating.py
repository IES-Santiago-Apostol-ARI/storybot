"""Phase 19 kiosk gating source-assertion tests (KSK-01..04)."""
from pathlib import Path
import re
import pytest
from fastapi.testclient import TestClient

SCRIPT_PATH = Path("static/children/script.js")


@pytest.fixture(scope="module")
def script_text():
    """Read the kiosk script once per module."""
    return SCRIPT_PATH.read_text(encoding="utf-8")


class TestKioskCapabilityFetch:
    """Source-assertion tests for capability fetch + window.aiEnabled wiring.

    KSK-01: kiosk discovers AI capability on page load and stores in
    window.aiEnabled with fail-closed semantics.
    """

    def test_fetch_capabilities_helper_defined(self, script_text):
        """fetchCapabilities async helper exists in script.js."""
        assert re.search(
            r"async\s+function\s+fetchCapabilities\s*\(", script_text
        ), "Missing async function fetchCapabilities()"

    def test_fetch_targets_capabilities_endpoint(self, script_text):
        """fetchCapabilities calls GET /api/capabilities."""
        assert "/api/capabilities" in script_text, (
            "Script does not reference /api/capabilities endpoint"
        )

    def test_fetch_has_timeout(self, script_text):
        """fetchCapabilities uses AbortController with a 500-5000ms timeout."""
        assert "AbortController" in script_text, (
            "Missing AbortController for fetch timeout"
        )
        # Extract the setTimeout delay value
        timeout_match = re.search(
            r"setTimeout\s*\(\s*\(\)\s*=>\s*controller\.abort\s*\(\s*\)\s*,\s*(\d+)\s*\)",
            script_text,
        )
        assert timeout_match, "Missing setTimeout -> controller.abort() pattern"
        timeout_ms = int(timeout_match.group(1))
        assert 500 <= timeout_ms <= 5000, (
            f"Timeout {timeout_ms}ms outside 500-5000ms range"
        )

    def test_fail_closed_initial_and_catch(self, script_text):
        """window.aiEnabled = false appears at least twice (initial + catch)."""
        count = script_text.count("window.aiEnabled = false")
        assert count >= 2, (
            f"Expected >= 2 occurrences of 'window.aiEnabled = false', got {count}"
        )

    def test_success_assignment_strict_boolean(self, script_text):
        """On success, window.aiEnabled is set via strict boolean comparison."""
        assert re.search(
            r"window\.aiEnabled\s*=\s*data\.ai_enabled\s*===\s*true", script_text
        ), "Missing strict boolean assignment: window.aiEnabled = data.ai_enabled === true"

    def test_dom_content_loaded_is_async(self, script_text):
        """DOMContentLoaded handler is async."""
        assert re.search(
            r"document\.addEventListener\s*\(\s*['\"]DOMContentLoaded['\"]\s*,\s*async\s*\(\s*\)\s*=>",
            script_text,
        ), "DOMContentLoaded handler is not async"

    def test_init_order_fetch_before_load_and_listener(self, script_text):
        """Init order: await fetchCapabilities -> loadStories -> startNFCListener."""
        # Extract the DOMContentLoaded handler body to avoid matching definitions
        dcl_match = re.search(
            r"document\.addEventListener\s*\(\s*['\"]DOMContentLoaded['\"]\s*,\s*async\s*\([^)]*\)\s*=>\s*\{",
            script_text,
        )
        assert dcl_match, "DOMContentLoaded async handler not found"
        dcl_body = script_text[dcl_match.end() :]
        # Find the closing of the handler (matching brace at same depth)
        depth = 1
        end = 0
        for i, ch in enumerate(dcl_body):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        handler_body = dcl_body[:end]

        fetch_pos = handler_body.find("await fetchCapabilities(")
        load_pos = handler_body.find("loadStories()")
        nfc_pos = handler_body.find("startNFCListener()")

        assert fetch_pos > 0, "await fetchCapabilities() not found in DCL handler"
        assert load_pos > 0, "loadStories() not found in DCL handler"
        assert nfc_pos > 0, "startNFCListener() not found in DCL handler"
        assert fetch_pos < load_pos < nfc_pos, (
            f"Init order wrong: fetchCapabilities at {fetch_pos}, "
            f"loadStories at {load_pos}, startNFCListener at {nfc_pos}"
        )

    def test_no_retry_loop(self, script_text):
        """fetchCapabilities appears exactly 2 times (definition + call)."""
        count = script_text.count("fetchCapabilities")
        assert count == 2, (
            f"Expected fetchCapabilities to appear exactly 2 times, got {count}"
        )

    def test_no_separate_api_helper_file(self):
        """No static/children/api.js helper file exists."""
        assert not Path("static/children/api.js").exists(), (
            "static/children/api.js exists — capability fetch should be inline"
        )

    def test_capabilities_endpoint_alive(self):
        """GET /api/capabilities returns 200 with boolean ai_enabled."""
        from app.main import app

        with TestClient(app) as client:
            response = client.get("/api/capabilities")
            assert response.status_code == 200
            data = response.json()
            assert "ai_enabled" in data
            assert isinstance(data["ai_enabled"], bool)
