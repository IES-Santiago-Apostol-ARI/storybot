"""Phase 25 admin updates-UI source-assertion tests (OTA-02).

Mirrors tests/test_admin_gating.py: module-scoped fixtures read the admin
frontend files and tests assert on string/regex patterns. One live test uses
the FastAPI TestClient against GET /api/updates/version (backend from Phase 23).
"""

import re
from pathlib import Path

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


def _extract_function_body(text, func_name):
    """Return the brace-balanced body of a named function definition."""
    match = re.search(
        r"(?:async\s+)?function\s+" + re.escape(func_name) + r"\s*\([^)]*\)\s*\{",
        text,
    )
    assert match is not None, f"function {func_name} not found"
    rest = text[match.end() :]
    depth = 1
    end = 0
    for i, ch in enumerate(rest):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    return rest[:end]


def _extract_dcl_body(text):
    """Extract the DOMContentLoaded handler body from the admin script."""
    dcl_match = re.search(
        r"document\.addEventListener\s*\(\s*['\"]DOMContentLoaded['\"]\s*,"
        r"\s*async\s*\([^)]*\)\s*=>\s*\{",
        text,
    )
    assert dcl_match is not None, "DOMContentLoaded async handler not found"
    rest = text[dcl_match.end() :]
    depth = 1
    end = 0
    for i, ch in enumerate(rest):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    return rest[:end]


class TestUpdateNotificationMarkup:
    """D-01, D-12: header badge icon + conditional Actualizaciones section."""

    def test_update_status_icon_exists(self, html_text):
        """An element id="update-status" exists with status-icon + hidden classes."""
        match = re.search(
            r'id="update-status"[^>]*class="([^"]*)"'
            r'|class="([^"]*)"[^>]*id="update-status"',
            html_text,
        )
        assert match, "No element with id='update-status' found"
        classes = match.group(1) or match.group(2)
        assert "status-icon" in classes, "update-status missing status-icon class"
        assert "hidden" in classes, "update-status missing hidden class"

    def test_update_badge_dot_child_exists(self, html_text):
        """A child element with class update-badge-dot exists."""
        assert (
            "update-badge-dot" in html_text
        ), "index.html missing update-badge-dot element"

    def test_updates_section_exists_hidden(self, html_text):
        """A section id="updates-section" exists with a hidden class."""
        match = re.search(
            r'<section[^>]*id="updates-section"[^>]*class="([^"]*)"'
            r'|<section[^>]*class="([^"]*)"[^>]*id="updates-section"',
            html_text,
        )
        assert match, "No <section> with id='updates-section' found"
        classes = match.group(1) or match.group(2)
        assert "hidden" in classes, "updates-section missing hidden class"

    def test_updates_info_exists(self, html_text):
        """id="updates-info" exists inside the updates section."""
        assert 'id="updates-info"' in html_text, "index.html missing id='updates-info'"

    def test_install_button_exists(self, html_text):
        """id="updates-install-btn" exists with text Instalar."""
        match = re.search(
            r'<button[^>]*id="updates-install-btn"[^>]*>\s*Instalar\s*</button>',
            html_text,
        )
        assert match, "No <button id='updates-install-btn'>Instalar</button> found"


class TestUpdateCheckWiring:
    """D-02, D-03, T-25-01: checkForUpdate fetch + gating + XSS-safe render."""

    def test_check_for_update_defined(self, script_text):
        """async function checkForUpdate is defined."""
        assert re.search(
            r"async\s+function\s+checkForUpdate\s*\(", script_text
        ), "Missing async function checkForUpdate()"

    def test_check_for_update_fetches_endpoint(self, script_text):
        """checkForUpdate fetches /api/updates/check."""
        body = _extract_function_body(script_text, "checkForUpdate")
        assert re.search(
            r"fetch\(['\"]/api/updates/check", body
        ), "checkForUpdate does not fetch /api/updates/check"

    def test_check_gates_on_update_available(self, script_text):
        """checkForUpdate gates reveal on data.update_available."""
        body = _extract_function_body(script_text, "checkForUpdate")
        assert (
            "update_available" in body
        ), "checkForUpdate does not reference update_available"

    def test_check_writes_short_hash(self, script_text):
        """#updates-info uses a 7-char truncation of remote_commit, not raw hash."""
        body = _extract_function_body(script_text, "checkForUpdate")
        assert re.search(
            r"remote_commit\s*\.\s*(?:slice|substring)\(\s*0\s*,\s*7\s*\)", body
        ), "checkForUpdate does not truncate remote_commit to first 7 chars"

    def test_check_renders_via_textcontent(self, script_text):
        """remote_commit is written via textContent, never innerHTML (T-25-01)."""
        body = _extract_function_body(script_text, "checkForUpdate")
        assert "textContent" in body, "checkForUpdate does not use textContent"
        assert (
            "innerHTML" not in body
        ), "checkForUpdate uses innerHTML — XSS risk (T-25-01)"

    def test_check_has_silent_catch(self, script_text):
        """checkForUpdate has a try/catch that swallows errors (no showMessage)."""
        body = _extract_function_body(script_text, "checkForUpdate")
        assert "catch" in body, "checkForUpdate has no catch block"
        assert (
            "showMessage" not in body
        ), "checkForUpdate calls showMessage — must fail silently (D-03)"

    def test_check_called_in_dom_content_loaded(self, script_text):
        """checkForUpdate() is invoked inside the DOMContentLoaded handler."""
        dcl = _extract_dcl_body(script_text)
        assert (
            "checkForUpdate()" in dcl
        ), "checkForUpdate() not called in DOMContentLoaded handler"

    def test_no_setinterval_for_checking(self, script_text):
        """No setInterval call references checkForUpdate (D-02 no polling)."""
        for m in re.finditer(r"setInterval\s*\(", script_text):
            window = script_text[m.start() : m.start() + 200]
            assert (
                "checkForUpdate" not in window
            ), "checkForUpdate referenced inside a setInterval — D-02 forbids polling"


class TestVersionFooter:
    """D-11: footer version line fetched from /api/updates/version."""

    def test_version_footer_markup_exists(self, html_text):
        """p id="version-footer" with class version-footer exists."""
        match = re.search(
            r'id="version-footer"[^>]*class="([^"]*)"'
            r'|class="([^"]*)"[^>]*id="version-footer"',
            html_text,
        )
        assert match, "No element with id='version-footer' found"
        classes = match.group(1) or match.group(2)
        assert (
            "version-footer" in classes
        ), "version-footer element missing version-footer class"

    def test_render_version_footer_defined(self, script_text):
        """async function renderVersionFooter is defined."""
        assert re.search(
            r"async\s+function\s+renderVersionFooter\s*\(", script_text
        ), "Missing async function renderVersionFooter()"

    def test_render_version_footer_fetches_endpoint(self, script_text):
        """renderVersionFooter fetches /api/updates/version."""
        body = _extract_function_body(script_text, "renderVersionFooter")
        assert re.search(
            r"fetch\(['\"]/api/updates/version", body
        ), "renderVersionFooter does not fetch /api/updates/version"

    def test_render_version_footer_writes_footer(self, script_text):
        """renderVersionFooter writes #version-footer via textContent."""
        body = _extract_function_body(script_text, "renderVersionFooter")
        assert (
            "version-footer" in body
        ), "renderVersionFooter does not reference version-footer"
        assert "textContent" in body, "renderVersionFooter does not use textContent"
        assert (
            "innerHTML" not in body
        ), "renderVersionFooter uses innerHTML — XSS risk (T-25-01)"

    def test_render_version_footer_called_in_dom_content_loaded(self, script_text):
        """renderVersionFooter() is invoked inside the DOMContentLoaded handler."""
        dcl = _extract_dcl_body(script_text)
        assert (
            "renderVersionFooter()" in dcl
        ), "renderVersionFooter() not called in DOMContentLoaded handler"

    def test_update_badge_dot_css_rule(self, css_text):
        """styles.css contains a .update-badge-dot rule."""
        assert (
            ".update-badge-dot" in css_text
        ), "styles.css missing .update-badge-dot rule"

    def test_version_footer_css_rule(self, css_text):
        """styles.css contains a .version-footer rule."""
        assert ".version-footer" in css_text, "styles.css missing .version-footer rule"

    def test_version_endpoint_alive(self):
        """GET /api/updates/version returns 200 with keys version and commit."""
        from app.main import app

        with TestClient(app) as client:
            response = client.get("/api/updates/version")
            assert response.status_code == 200
            data = response.json()
            assert "version" in data
            assert "commit" in data


# === Plan 02 (OTA-03): install flow, modal, restart/reconnect ===

_INSTALL_STAGES = ("fetching", "updating", "syncing", "checking", "restarting")


class TestStageLabelMapping:
    """D-06: each backend stage maps to a non-empty Spanish label."""

    def test_stage_labels_object_defined(self, script_text):
        """A STAGE_LABELS const object literal is defined."""
        assert re.search(
            r"const\s+STAGE_LABELS\s*=\s*\{", script_text
        ), "Missing const STAGE_LABELS = { ... } mapping"

    def test_all_stages_mapped(self, script_text):
        """Each of the five backend stages is mapped to a quoted non-empty string."""
        match = re.search(r"const\s+STAGE_LABELS\s*=\s*\{(.*?)\}", script_text, re.S)
        assert match, "STAGE_LABELS object literal not found"
        body = match.group(1)
        for stage in _INSTALL_STAGES:
            m = re.search(re.escape(stage) + r"['\"]?\s*:\s*['\"]([^'\"]+)['\"]", body)
            assert m, f"STAGE_LABELS missing a mapping for stage '{stage}'"
            assert m.group(1).strip(), f"stage '{stage}' maps to an empty string"

    def test_stage_label_helper_defined(self, script_text):
        """A stageLabel(stage) helper function or arrow is defined."""
        assert re.search(
            r"(?:function\s+stageLabel\s*\(|stageLabel\s*=\s*(?:function|\())",
            script_text,
        ), "Missing stageLabel() helper"


class TestInstallModalMarkup:
    """D-04, D-06, D-07: install progress modal markup."""

    def test_updates_modal_exists_with_hidden_attribute(self, html_text):
        """div id="updates-modal" is a .modal-overlay using the bare hidden attr."""
        match = re.search(r'<div[^>]*id="updates-modal"[^>]*>', html_text)
        assert match, "No <div id='updates-modal'> found"
        tag = match.group(0)
        assert "modal-overlay" in tag, "updates-modal missing modal-overlay class"
        # Bare hidden attribute convention (not class="hidden")
        assert re.search(r"\shidden(?:\s|>|=)", tag), (
            "updates-modal must use the bare hidden attribute (modal-overlay "
            "convention), not the hidden class"
        )

    def test_updates_modal_content_class(self, html_text):
        """A .modal-content with the updates-modal class exists."""
        assert re.search(
            r'class="[^"]*modal-content[^"]*updates-modal'
            r'|class="[^"]*updates-modal[^"]*modal-content',
            html_text,
        ), "Missing .modal-content.updates-modal element"

    def test_status_line_exists(self, html_text):
        """id="updates-status-line" exists for the single in-place status line."""
        assert (
            'id="updates-status-line"' in html_text
        ), "index.html missing id='updates-status-line'"

    def test_spinner_exists(self, html_text):
        """An element with class updates-spinner exists in the modal."""
        assert (
            "updates-spinner" in html_text
        ), "index.html missing updates-spinner element"

    def test_modal_error_exists_hidden(self, html_text):
        """id="updates-modal-error" exists and starts hidden."""
        match = re.search(
            r'id="updates-modal-error"[^>]*class="([^"]*)"'
            r'|class="([^"]*)"[^>]*id="updates-modal-error"',
            html_text,
        )
        assert match, "No element with id='updates-modal-error' found"
        classes = match.group(1) or match.group(2)
        assert "hidden" in classes, "updates-modal-error must start hidden"

    def test_modal_action_button_exists(self, html_text):
        """A modal-actions button id="updates-modal-action" exists (retry/reload)."""
        assert (
            'id="updates-modal-action"' in html_text
        ), "index.html missing id='updates-modal-action' button"


class TestInstallModalStyles:
    """D-06: spinner keyframes + modal-content rule."""

    def test_spinner_rule_exists(self, css_text):
        """styles.css contains a .updates-spinner rule."""
        assert (
            ".updates-spinner" in css_text
        ), "styles.css missing .updates-spinner rule"

    def test_spin_keyframes_exist(self, css_text):
        """styles.css contains an @keyframes spin (or equivalent rotation)."""
        assert re.search(
            r"@keyframes\s+spin\b", css_text
        ), "styles.css missing @keyframes spin"

    def test_updates_modal_content_rule(self, css_text):
        """styles.css contains a .modal-content.updates-modal rule."""
        assert re.search(
            r"\.modal-content\.updates-modal|\.updates-modal\.modal-content",
            css_text,
        ), "styles.css missing .modal-content.updates-modal rule"


class TestInstallFlowWiring:
    """D-05, D-06, D-07, T-25-02: installUpdate POST-SSE flow + button wiring."""

    def test_install_update_defined(self, script_text):
        """async function installUpdate is defined."""
        assert re.search(
            r"async\s+function\s+installUpdate\s*\(", script_text
        ), "Missing async function installUpdate()"

    def test_install_opens_modal_via_hidden_attr(self, script_text):
        """installUpdate opens #updates-modal via modal.hidden = false."""
        body = _extract_function_body(script_text, "installUpdate")
        assert "updates-modal" in body, "installUpdate does not reference updates-modal"
        assert re.search(
            r"\.hidden\s*=\s*false", body
        ), "installUpdate must open the modal via modal.hidden = false"

    def test_install_does_not_use_eventsource(self, script_text):
        """installUpdate must NOT use EventSource (apply is a POST)."""
        body = _extract_function_body(script_text, "installUpdate")
        assert (
            "EventSource" not in body
        ), "installUpdate must not use EventSource — apply is POST (use getReader)"

    def test_install_posts_to_apply(self, script_text):
        """installUpdate POSTs to /api/updates/apply."""
        body = _extract_function_body(script_text, "installUpdate")
        assert re.search(
            r"fetch\(['\"]/api/updates/apply", body
        ), "installUpdate does not fetch /api/updates/apply"
        # method POST appears near the apply fetch
        assert re.search(
            r"method\s*:\s*['\"]POST['\"]", body
        ), "installUpdate apply fetch missing method: 'POST'"

    def test_install_consumes_stream_via_getreader(self, script_text):
        """installUpdate reads the SSE stream via response.body.getReader()."""
        body = _extract_function_body(script_text, "installUpdate")
        assert (
            "getReader()" in body
        ), "installUpdate does not consume the stream via getReader()"

    def test_install_handles_error_stage(self, script_text):
        """installUpdate has a stage === 'error' branch revealing inline error."""
        body = _extract_function_body(script_text, "installUpdate")
        assert re.search(
            r"['\"]error['\"]", body
        ), "installUpdate does not branch on the 'error' stage"
        assert (
            "updates-modal-error" in body
        ), "installUpdate error branch does not reveal #updates-modal-error"

    def test_status_line_via_textcontent_not_innerhtml(self, script_text):
        """Stage labels render via textContent, never innerHTML (T-25-02)."""
        body = _extract_function_body(script_text, "installUpdate")
        assert "textContent" in body, "installUpdate does not use textContent"
        assert (
            "innerHTML" not in body
        ), "installUpdate uses innerHTML — XSS risk (T-25-02)"

    def test_install_button_wired_in_init(self, script_text):
        """initUpdatesSection binds the install button and is called from DCL."""
        assert re.search(
            r"function\s+initUpdatesSection\s*\(", script_text
        ), "Missing initUpdatesSection() function"
        init_body = _extract_function_body(script_text, "initUpdatesSection")
        assert (
            "updates-install-btn" in init_body
        ), "initUpdatesSection does not bind #updates-install-btn"
        assert (
            "installUpdate" in init_body
        ), "initUpdatesSection does not wire installUpdate"
        dcl = _extract_dcl_body(script_text)
        assert (
            "initUpdatesSection()" in dcl
        ), "initUpdatesSection() not called in DOMContentLoaded handler"


class TestRestartReconnect:
    """D-08, D-09, D-10: restart poll loop + hash-prefix success detection."""

    def test_poll_for_restart_defined(self, script_text):
        """A pollForRestart function is defined."""
        assert re.search(
            r"function\s+pollForRestart\s*\(", script_text
        ), "Missing pollForRestart() function"

    def test_poll_fetches_version(self, script_text):
        """pollForRestart fetches /api/updates/version."""
        body = _extract_function_body(script_text, "pollForRestart")
        assert re.search(
            r"fetch\(['\"]/api/updates/version", body
        ), "pollForRestart does not fetch /api/updates/version"

    def test_poll_has_60s_budget(self, script_text):
        """pollForRestart uses a ~60s budget with a Date.now()/elapsed comparison."""
        body = _extract_function_body(script_text, "pollForRestart")
        assert re.search(
            r"60000|60\s*\*\s*1000", body
        ), "pollForRestart missing a 60000ms / 60s budget"
        assert (
            "Date.now()" in body
        ), "pollForRestart missing a Date.now() elapsed comparison"

    def test_baseline_sourced_from_check_full_commit(self, script_text):
        """The pre-install baseline is the FULL local_commit from /api/updates/check."""
        body = _extract_function_body(script_text, "installUpdate")
        assert (
            "local_commit" in body
        ), "installUpdate does not source the baseline from check.local_commit"
        # Baseline derives from /check, not /version
        assert re.search(
            r"fetch\(['\"]/api/updates/check", body
        ), "installUpdate does not read /api/updates/check for the baseline"

    def test_success_uses_startswith_prefix(self, script_text):
        """Success detection uses a startsWith prefix check (D-09 guard)."""
        body = _extract_function_body(script_text, "pollForRestart")
        assert re.search(
            r"\.startsWith\(", body
        ), "pollForRestart success detection must use a startsWith prefix check"

    def test_success_not_raw_inequality(self, script_text):
        """Success is NOT gated on a raw version.commit !== baseline (D-09 guard)."""
        body = _extract_function_body(script_text, "pollForRestart")
        # No bare inequality between the version commit and the full baseline.
        assert not re.search(r"version\.commit\s*!==\s*\w*[Cc]ommit", body), (
            "pollForRestart decides success via a raw !== between commit and the "
            "baseline — short never equals full, would fire on tick 1 (D-09)"
        )

    def test_reload_on_success_not_timeout(self, script_text):
        """reload fires on the new-commit branch, not unconditionally on timeout."""
        body = _extract_function_body(script_text, "pollForRestart")
        assert (
            "window.location.reload()" in body
        ), "pollForRestart never calls window.location.reload()"
        # The reload must be associated with the startsWith/isNewCommit success
        # region — it must NOT be the lone action of the timeout handler. We assert
        # a Recargar action button is shown on timeout instead.
        assert "updates-modal-action" in body, (
            "pollForRestart timeout path must show a manual Recargar action "
            "(#updates-modal-action), not auto-reload (D-10)"
        )
