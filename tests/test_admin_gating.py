"""Phase 20 admin gating source-assertion tests (ADM-06..10)."""
from pathlib import Path
import re
import pytest
from fastapi.testclient import TestClient

SCRIPT_PATH = Path("static/admin/script.js")
HTML_PATH = Path("static/admin/index.html")
CSS_PATH = Path("static/admin/styles.css")


@pytest.fixture(scope="module")
def script_text():
    """Read the admin script once per module."""
    return SCRIPT_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def html_text():
    """Read the admin HTML once per module."""
    return HTML_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css_text():
    """Read the admin CSS once per module."""
    return CSS_PATH.read_text(encoding="utf-8")


class TestAdminCapabilityFetch:
    """Source-assertion tests for admin capability fetch + badge wiring.

    ADM-06: admin fetches /api/capabilities on DOMContentLoaded before
    loadStories(), stores result in window.aiEnabled (fail-closed).
    ADM-10: capability badge shows device mode in header.
    """

    # -- ADM-06: Capability fetch wiring ---------------------------------

    def test_fetch_capabilities_helper_defined(self, script_text):
        """fetchCapabilities async helper exists in admin script.js."""
        assert re.search(
            r"async\s+function\s+fetchCapabilities\s*\(", script_text
        ), "Missing async function fetchCapabilities()"

    def test_fetch_targets_capabilities_endpoint(self, script_text):
        """fetchCapabilities calls GET /api/capabilities."""
        assert "/api/capabilities" in script_text, (
            "Script does not reference /api/capabilities endpoint"
        )

    def test_fetch_has_timeout(self, script_text):
        """fetchCapabilities uses AbortController with 1500ms timeout."""
        assert "AbortController" in script_text, (
            "Missing AbortController for fetch timeout"
        )
        timeout_match = re.search(
            r"setTimeout\s*\(\s*\(\)\s*=>\s*controller\.abort\s*\(\s*\)\s*,\s*(\d+)\s*\)",
            script_text,
        )
        assert timeout_match, "Missing setTimeout -> controller.abort() pattern"
        timeout_ms = int(timeout_match.group(1))
        assert timeout_ms == 1500, (
            f"Expected 1500ms timeout, got {timeout_ms}ms"
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

    def test_init_order_fetch_before_load_stories(self, script_text):
        """Init order: await fetchCapabilities -> badge -> loadStories."""
        # Extract the DOMContentLoaded handler body
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

        assert fetch_pos > 0, "await fetchCapabilities() not found in DCL handler"
        assert load_pos > 0, "loadStories() not found in DCL handler"
        assert fetch_pos < load_pos, (
            f"Init order wrong: fetchCapabilities at {fetch_pos}, "
            f"loadStories at {load_pos}"
        )

    def test_no_retry_loop(self, script_text):
        """fetchCapabilities appears exactly 2 times (definition + call)."""
        count = script_text.count("fetchCapabilities")
        assert count == 2, (
            f"Expected fetchCapabilities to appear exactly 2 times, got {count}"
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

    # -- ADM-10: Badge ---------------------------------------------------

    def test_badge_html_placeholder_exists(self, html_text):
        """index.html contains span with class capability-badge."""
        assert "capability-badge" in html_text, (
            "index.html missing capability-badge class"
        )

    def test_badge_position_between_h1_and_status_icons(self, html_text):
        """Badge appears after </h1> and before class='status-icons'."""
        h1_end = html_text.find("</h1>")
        badge_pos = html_text.find("capability-badge")
        status_pos = html_text.find('class="status-icons"')
        assert h1_end > 0, "</h1> not found in index.html"
        assert badge_pos > 0, "capability-badge not found in index.html"
        assert status_pos > 0, 'class="status-icons" not found in index.html'
        assert h1_end < badge_pos < status_pos, (
            f"Badge position wrong: h1_end={h1_end}, badge={badge_pos}, "
            f"status_icons={status_pos}"
        )

    def test_badge_placeholder_text(self, html_text):
        """Badge placeholder element contains 'Modo: ...' initial text."""
        assert re.search(
            r'<span\s+class="capability-badge">Modo: \.\.\.</span>', html_text
        ), "Missing <span class='capability-badge'>Modo: ...</span> placeholder"

    def test_js_writes_modo_completo(self, script_text):
        """Script contains literal 'Modo: Completo' string."""
        assert "Modo: Completo" in script_text, (
            "Script missing 'Modo: Completo' literal"
        )

    def test_js_writes_modo_basico(self, script_text):
        """Script contains literal 'Modo: Basico (sin IA)' string."""
        assert "Modo: Basico (sin IA)" in script_text, (
            "Script missing 'Modo: Basico (sin IA)' literal"
        )

    # -- CSS -------------------------------------------------------------

    def test_badge_css_rule_exists(self, css_text):
        """styles.css contains .capability-badge rule."""
        assert ".capability-badge" in css_text, (
            "styles.css missing .capability-badge rule"
        )


def _extract_dcl_body(text):
    """Extract the DOMContentLoaded handler body from the admin script."""
    dcl_match = re.search(
        r"document\.addEventListener\s*\(\s*['\"]DOMContentLoaded['\"]\s*,\s*async\s*\([^)]*\)\s*=>\s*\{",
        text,
    )
    assert dcl_match is not None, "DOMContentLoaded async handler not found"
    dcl_body = text[dcl_match.end() :]
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
    return dcl_body[:end]


class TestAdminSectionGating:
    """Source-assertion tests for ADM-07, ADM-08, ADM-09 -- section hiding + skipped fetches."""

    # -- ADM-07: Cards section hidden ------------------------------------

    def test_cards_section_hidden(self, script_text):
        """cards-section gets classList.add('hidden') inside DOMContentLoaded."""
        dcl_body = _extract_dcl_body(script_text)
        # Find the if (!window.aiEnabled) block
        gate_idx = dcl_body.find("if (!window.aiEnabled)")
        assert gate_idx > 0, "if (!window.aiEnabled) block not found in DCL handler"
        gate_block = dcl_body[gate_idx:]
        # Extract the gated block body
        brace_start = gate_block.find("{")
        assert brace_start > 0
        gate_body = gate_block[brace_start + 1 :]
        depth = 1
        end = 0
        for i, ch in enumerate(gate_body):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        gated_content = gate_body[:end]
        assert "cards-section" in gated_content, (
            "cards-section not referenced inside if (!window.aiEnabled) block"
        )
        assert "classList.add('hidden')" in gated_content, (
            "classList.add('hidden') not found inside if (!window.aiEnabled) block"
        )

    def test_cards_section_gating_conditional(self, script_text):
        """cards-section hide appears inside an if (!window.aiEnabled) block."""
        dcl_body = _extract_dcl_body(script_text)
        gate_idx = dcl_body.find("if (!window.aiEnabled)")
        assert gate_idx > 0, "if (!window.aiEnabled) block not found in DCL handler"
        # Find cards-section with classList.add('hidden') after the gate
        search_area = dcl_body[gate_idx:]
        cards_hide_idx = search_area.find("cards-section")
        assert cards_hide_idx > 0, "cards-section not found after if (!window.aiEnabled)"
        # The cards-section must appear before the closing brace of the if block
        assert "classList.add('hidden')" in search_area[: cards_hide_idx + 200], (
            "cards-section does not have classList.add('hidden') in gated block"
        )

    # -- ADM-08: Generated section hidden --------------------------------

    def test_generated_section_hidden(self, script_text):
        """generated-section gets classList.add('hidden') inside DOMContentLoaded."""
        dcl_body = _extract_dcl_body(script_text)
        gate_idx = dcl_body.find("if (!window.aiEnabled)")
        assert gate_idx > 0, "if (!window.aiEnabled) block not found in DCL handler"
        gate_block = dcl_body[gate_idx:]
        brace_start = gate_block.find("{")
        gate_body = gate_block[brace_start + 1 :]
        depth = 1
        end = 0
        for i, ch in enumerate(gate_body):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        gated_content = gate_body[:end]
        assert "generated-section" in gated_content, (
            "generated-section not referenced inside if (!window.aiEnabled) block"
        )
        assert "classList.add('hidden')" in gated_content

    def test_generated_section_gating_conditional(self, script_text):
        """generated-section hide appears inside if (!window.aiEnabled) block."""
        dcl_body = _extract_dcl_body(script_text)
        gate_idx = dcl_body.find("if (!window.aiEnabled)")
        assert gate_idx > 0, "if (!window.aiEnabled) block not found in DCL handler"
        search_area = dcl_body[gate_idx:]
        gen_hide_idx = search_area.find("generated-section")
        assert gen_hide_idx > 0, (
            "generated-section not found after if (!window.aiEnabled)"
        )
        assert "classList.add('hidden')" in search_area[: gen_hide_idx + 200], (
            "generated-section does not have classList.add('hidden') in gated block"
        )

    # -- ADM-09: Buttons hidden individually -----------------------------

    def test_register_parameter_btn_hidden(self, script_text):
        """register-parameter-btn gets classList.add('hidden') in gating block."""
        dcl_body = _extract_dcl_body(script_text)
        gate_idx = dcl_body.find("if (!window.aiEnabled)")
        assert gate_idx > 0
        search_area = dcl_body[gate_idx:]
        assert "register-parameter-btn" in search_area, (
            "register-parameter-btn not found in gating block"
        )
        assert "classList.add('hidden')" in search_area, (
            "classList.add('hidden') not found in gating block"
        )

    def test_register_go_btn_hidden(self, script_text):
        """register-go-btn gets classList.add('hidden') in gating block."""
        dcl_body = _extract_dcl_body(script_text)
        gate_idx = dcl_body.find("if (!window.aiEnabled)")
        assert gate_idx > 0
        search_area = dcl_body[gate_idx:]
        assert "register-go-btn" in search_area, (
            "register-go-btn not found in gating block"
        )
        assert "classList.add('hidden')" in search_area

    # -- D-09: Skipped fetches -------------------------------------------

    def test_load_cards_wrapped_in_ai_check(self, script_text):
        """loadCards() call in DCL handler is wrapped in if (window.aiEnabled)."""
        dcl_body = _extract_dcl_body(script_text)
        ai_check_idx = dcl_body.find("if (window.aiEnabled)")
        assert ai_check_idx > 0, "if (window.aiEnabled) wrapper not found in DCL handler"
        # Find loadCards() call (not the function definition)
        load_cards_idx = dcl_body.find("loadCards()")
        assert load_cards_idx > 0, "loadCards() not found in DCL handler"
        assert ai_check_idx < load_cards_idx, (
            f"if (window.aiEnabled) at {ai_check_idx} must come before "
            f"loadCards() at {load_cards_idx}"
        )
        # Verify loadCards() is inside a window.aiEnabled wrapper
        between = dcl_body[ai_check_idx : load_cards_idx + len("loadCards()")]
        assert "loadCards()" in between

    def test_load_generated_stories_wrapped_in_ai_check(self, script_text):
        """loadGeneratedStories() call in DCL handler is wrapped in if (window.aiEnabled)."""
        dcl_body = _extract_dcl_body(script_text)
        # Find all if (window.aiEnabled) occurrences
        search_from = 0
        wrappers = []
        while True:
            idx = dcl_body.find("if (window.aiEnabled)", search_from)
            if idx == -1:
                break
            wrappers.append(idx)
            search_from = idx + 1
        assert len(wrappers) >= 1, "if (window.aiEnabled) wrapper not found in DCL handler"
        load_gen_idx = dcl_body.find("loadGeneratedStories()")
        assert load_gen_idx > 0, "loadGeneratedStories() not found in DCL handler"
        # At least one wrapper must be before loadGeneratedStories()
        found = False
        for w in wrappers:
            if w < load_gen_idx:
                found = True
                break
        assert found, (
            "No if (window.aiEnabled) wrapper found before loadGeneratedStories()"
        )

    # -- Regression anchors -----------------------------------------------

    def test_load_stories_not_gated(self, script_text):
        """loadStories() is NOT wrapped in if (window.aiEnabled)."""
        dcl_body = _extract_dcl_body(script_text)
        load_stories_idx = dcl_body.find("loadStories()")
        assert load_stories_idx > 0, "loadStories() not found in DCL handler"
        # Check the text between fetchCapabilities and loadStories
        fetch_idx = dcl_body.find("await fetchCapabilities(")
        assert fetch_idx > 0
        between = dcl_body[fetch_idx:load_stories_idx]
        assert "if (window.aiEnabled)" not in between, (
            "loadStories() appears to be wrapped in if (window.aiEnabled) -- must be unconditional"
        )

    def test_no_defensive_check_in_start_card_registration(self, script_text):
        """startCardRegistration function body does NOT contain window.aiEnabled (D-10)."""
        func_match = re.search(
            r"function\s+startCardRegistration\s*\([^)]*\)\s*\{", script_text
        )
        assert func_match, "function startCardRegistration not found"
        func_body_start = script_text[func_match.end() :]
        depth = 1
        end = 0
        for i, ch in enumerate(func_body_start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        func_body = func_body_start[:end]
        assert "window.aiEnabled" not in func_body, (
            "startCardRegistration contains window.aiEnabled check -- violates D-10 (YAGNI)"
        )

    def test_status_polling_not_gated(self, script_text):
        """startStatusPolling() is NOT wrapped in if (window.aiEnabled)."""
        dcl_body = _extract_dcl_body(script_text)
        status_idx = dcl_body.find("startStatusPolling()")
        assert status_idx > 0, "startStatusPolling() not found in DCL handler"
        # Check if there's an if (window.aiEnabled) wrapper around it
        # Find all wrapper start/end positions
        search_from = 0
        wrapper_ranges = []
        while True:
            wrapper_start = dcl_body.find("if (window.aiEnabled)", search_from)
            if wrapper_start == -1:
                break
            # Find the closing brace
            brace_start = dcl_body.find("{", wrapper_start)
            if brace_start == -1:
                break
            depth = 1
            end = brace_start + 1
            for i in range(brace_start + 1, len(dcl_body)):
                if dcl_body[i] == "{":
                    depth += 1
                elif dcl_body[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            wrapper_ranges.append((wrapper_start, end))
            search_from = wrapper_start + 1
        for start, end in wrapper_ranges:
            assert not (start < status_idx < end), (
                "startStatusPolling() is inside an if (window.aiEnabled) wrapper -- must be unconditional"
            )

    def test_four_hidden_targets_in_gating_block(self, script_text):
        """The if (!window.aiEnabled) block has >= 4 classList.add('hidden') calls."""
        dcl_body = _extract_dcl_body(script_text)
        gate_idx = dcl_body.find("if (!window.aiEnabled)")
        assert gate_idx > 0, "if (!window.aiEnabled) block not found in DCL handler"
        gate_block = dcl_body[gate_idx:]
        brace_start = gate_block.find("{")
        gate_body = gate_block[brace_start + 1 :]
        depth = 1
        end = 0
        for i, ch in enumerate(gate_body):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        gated_content = gate_body[:end]
        count = gated_content.count("classList.add('hidden')")
        assert count >= 4, (
            f"Expected >= 4 classList.add('hidden') in gating block, got {count}"
        )
