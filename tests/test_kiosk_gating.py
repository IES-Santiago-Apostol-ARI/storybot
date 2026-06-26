"""Phase 19 kiosk gating source-assertion tests (KSK-01..04)."""
import re
import subprocess
from pathlib import Path

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

    def test_self_heals_capability_fetch_on_failure(self, script_text):
        """Capability fetch self-heals the boot race on a keyboard-less kiosk.

        Revises the original KSK-01 / D-02 "no retry" decision: a single
        fail-closed fetch wedged window.aiEnabled=false forever if it lost the
        race against backend startup, and the kiosk never reloads to recover.
        The single-attempt helper still exists (awaited at boot for a fast
        initial value), but a clean 2xx is authoritative while
        network/timeout/non-2xx failures retry with backoff via setTimeout.
        """
        # Single-attempt helper still present (fail-closed, returns a status).
        assert re.search(
            r"async\s+function\s+fetchCapabilitiesOnce\s*\(", script_text
        ), "Missing single-attempt fetchCapabilitiesOnce() helper"
        # The orchestrating fetchCapabilities re-attempts on failure.
        assert "setTimeout(retry" in script_text, (
            "Missing background retry scheduling for capability fetch"
        )
        # Backoff is bounded (no unbounded hammering of the endpoint).
        assert "maxDelay" in script_text, "Missing bounded backoff cap"

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


# ---------------------------------------------------------------------------
# Helper for TestKioskNfcGating
# ---------------------------------------------------------------------------

def _branch_range(text, start_marker, end_marker):
    """Return (start, end) indices for the code between two markers.

    The start index points to the *first character* of the start_marker line.
    The end index points to the *first character* of the end_marker line.
    """
    start = text.find(start_marker)
    assert start != -1, f"Start marker not found: {start_marker!r}"
    end = text.find(end_marker, start + len(start_marker))
    assert end != -1, f"End marker not found after start: {end_marker!r}"
    return start, end


class TestKioskNfcGating:
    """Source-assertion tests for NFC branch gating on non-AI devices.

    KSK-02: parameter + GO card branches are gated.
    KSK-03: showThinkingOverlay never fires on non-AI path.
    KSK-04: curated playback paths are byte-untouched.
    """

    # -- Literal guard presence ------------------------------------------

    def test_guard_literal_appears_twice(self, script_text):
        """The exact guard text appears at least twice in script.js."""
        guard = "if (!window.aiEnabled) { playUISound('tap'); return; }"
        count = script_text.count(guard)
        assert count >= 2, (
            f"Expected >= 2 occurrences of guard, got {count}"
        )

    # -- Parameter branch ordering ---------------------------------------

    def test_parameter_guard_before_state_mutation(self, script_text):
        """Guard sits between card_type==='parameter' and collectingParams.push."""
        param_start = script_text.find("if (card_type === 'parameter')")
        assert param_start != -1, "parameter branch not found"
        push_idx = script_text.find("collectingParams.push", param_start)
        assert push_idx != -1, "collectingParams.push after param branch not found"
        guard_idx = script_text.find(
            "if (!window.aiEnabled)", param_start
        )
        assert guard_idx != -1, "No window.aiEnabled guard in parameter branch"
        assert param_start < guard_idx < push_idx, (
            f"Guard at {guard_idx} not between param_start ({param_start}) "
            f"and push ({push_idx})"
        )

    def test_parameter_guard_before_chip_render(self, script_text):
        """Guard precedes renderParameterChips and parameter-display."""
        param_start = script_text.find("if (card_type === 'parameter')")
        guard_idx = script_text.find(
            "if (!window.aiEnabled)", param_start
        )
        assert guard_idx != -1, "No guard found in parameter branch"
        chips_idx = script_text.find("renderParameterChips", param_start)
        assert chips_idx != -1, "renderParameterChips not found after param branch"
        display_idx = script_text.find("parameter-display", param_start)
        assert display_idx != -1, "parameter-display not found after param branch"
        assert guard_idx < chips_idx, (
            f"Guard at {guard_idx} must precede renderParameterChips at {chips_idx}"
        )
        assert guard_idx < display_idx, (
            f"Guard at {guard_idx} must precede parameter-display at {display_idx}"
        )

    # -- GO branch ordering ----------------------------------------------

    def test_go_guard_before_empty_params_branch(self, script_text):
        """Guard in GO branch sits before 'if (collectingParams.length === 0)'."""
        go_start = script_text.find("if (card_type === 'go')")
        assert go_start != -1, "GO branch not found"
        empty_check = script_text.find(
            "if (collectingParams.length === 0)", go_start
        )
        assert empty_check != -1, "empty-params check not found in GO branch"
        guard_idx = script_text.find("if (!window.aiEnabled)", go_start)
        assert guard_idx != -1, "No guard found in GO branch"
        assert go_start < guard_idx < empty_check, (
            f"GO guard at {guard_idx} not between go_start ({go_start}) "
            f"and empty_check ({empty_check})"
        )

    # -- showThinkingOverlay not defensively modified ---------------------

    def test_no_defensive_check_inside_show_thinking_overlay(self, script_text):
        """showThinkingOverlay body must NOT contain window.aiEnabled."""
        fn_start = script_text.find("function showThinkingOverlay(")
        assert fn_start != -1, "showThinkingOverlay function not found"
        # Find the opening brace
        brace_start = script_text.find("{", fn_start)
        depth = 1
        end = brace_start + 1
        while depth > 0 and end < len(script_text):
            if script_text[end] == "{":
                depth += 1
            elif script_text[end] == "}":
                depth -= 1
            end += 1
        body = script_text[brace_start:end]
        assert "window.aiEnabled" not in body, (
            "showThinkingOverlay body must not reference window.aiEnabled (D-08)"
        )

    def test_show_thinking_overlay_only_called_inside_gated_paths(
        self, script_text
    ):
        """showThinkingOverlay() call inside GO branch is after the guard."""
        go_start = script_text.find("if (card_type === 'go')")
        assert go_start != -1, "GO branch not found"
        guard_idx = script_text.find("if (!window.aiEnabled)", go_start)
        # Find showThinkingOverlay() call within GO branch
        go_end = script_text.find("return;", script_text.find("showThinkingOverlay()", go_start))
        go_branch = script_text[go_start:go_end] if go_end != -1 else script_text[go_start:]
        overlay_call = script_text.find("showThinkingOverlay()", go_start)
        assert overlay_call != -1, "showThinkingOverlay() call not found in GO branch"
        if guard_idx != -1:
            assert guard_idx < overlay_call, (
                f"Guard at {guard_idx} must precede showThinkingOverlay call at {overlay_call}"
            )

    # -- KSK-04: Untouched branches --------------------------------------

    def test_story_branch_byte_untouched(self, script_text):
        """Story branch must not contain window.aiEnabled."""
        start, end = _branch_range(
            script_text,
            "if (card_type === 'story') {",
            "// Unknown card",
        )
        branch = script_text[start:end]
        assert "window.aiEnabled" not in branch, (
            "Story branch must not contain window.aiEnabled (KSK-04)"
        )

    def test_story_retap_branch_byte_untouched(self, script_text):
        """Story retap branch must not contain window.aiEnabled."""
        start, end = _branch_range(
            script_text,
            "// Story card retap to pause/resume (existing behavior)",
            "// Parameter card",
        )
        branch = script_text[start:end]
        assert "window.aiEnabled" not in branch, (
            "Story retap branch must not contain window.aiEnabled (KSK-04)"
        )

    def test_legacy_fallback_branch_byte_untouched(self, script_text):
        """Legacy fallback branch must not contain window.aiEnabled."""
        start, end = _branch_range(
            script_text,
            "// Legacy fallback (no card_type field)",
            "} catch (err)",
        )
        branch = script_text[start:end]
        assert "window.aiEnabled" not in branch, (
            "Legacy fallback branch must not contain window.aiEnabled (KSK-04)"
        )

    def test_unknown_card_branch_byte_untouched(self, script_text):
        """Unknown card branch must not contain window.aiEnabled."""
        start, end = _branch_range(
            script_text,
            "if (card_type === 'unknown') {",
            "// Legacy fallback",
        )
        branch = script_text[start:end]
        assert "window.aiEnabled" not in branch, (
            "Unknown card branch must not contain window.aiEnabled (KSK-04)"
        )

    # -- Backend contract unchanged --------------------------------------

    def test_backend_nfc_contract_unchanged(self):
        """Existing NFC API tests still pass (no backend regression)."""
        result = subprocess.run(
            ["uv", "run", "pytest", "tests/test_api/test_nfc.py", "-x", "--tb=short"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"Backend NFC tests failed:\n{result.stdout}\n{result.stderr}"
        )

    # -- D-03: Blocked tap is sound-only ---------------------------------

    def test_blocked_tap_is_sound_only(self, script_text):
        """The guard line and its immediate context contain ONLY playUISound."""
        guard = "if (!window.aiEnabled) { playUISound('tap'); return; }"
        guard_idx = script_text.find(guard)
        assert guard_idx != -1, "Guard text not found"
        # Check the first guard (parameter branch)
        param_start = script_text.find("if (card_type === 'parameter')")
        first_guard = script_text.find(guard, param_start)
        if first_guard != -1:
            context = script_text[first_guard - 80 : first_guard + len(guard) + 80]
            forbidden = [
                "classList.add",
                "transitionTo(",
                "setLED",
                "console.log",
                "console.warn",
            ]
            for token in forbidden:
                assert token not in context, (
                    f"Guard context contains forbidden token '{token}' — "
                    f"blocked tap must be sound-only (D-03)"
                )
