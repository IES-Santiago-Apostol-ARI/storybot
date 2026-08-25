"""Kiosk SSE reconnection contract.

The kiosk lost every NFC tap after a backend restart: nginx answered the
in-flight `/api/nfc/read` reconnect with 502, and per the HTML spec an
EventSource that receives an HTTP error *fails the connection* — readyState
goes to CLOSED and the browser never retries. The page kept rendering
normally while silently ignoring every card, which is the worst possible
failure mode in front of a child.

The reconnect policy itself is asserted behaviourally in
tests/js/sse_reconnect.test.cjs (driven by node --test). The assertions here
guard the wiring: the helper ships, the kiosk loads it, and neither kiosk
stream falls back to the bare `new EventSource(...)` that caused the outage.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

SSE_HELPER = Path("static/shared/sse.js")
KIOSK_SCRIPT = Path("static/children/script.js")
KIOSK_HTML = Path("static/children/index.html")


@pytest.fixture(scope="module")
def kiosk_script():
    return KIOSK_SCRIPT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def kiosk_html():
    return KIOSK_HTML.read_text(encoding="utf-8")


class TestHelperShips:
    def test_helper_file_exists(self):
        assert SSE_HELPER.exists(), f"{SSE_HELPER} must ship the reconnect helper"

    def test_helper_is_loadable_outside_the_browser(self):
        """The helper is exported for node --test; keep that seam intact."""
        assert "module.exports" in SSE_HELPER.read_text(encoding="utf-8"), (
            "sse.js must export createReconnectingEventSource under CommonJS so "
            "tests/js/sse_reconnect.test.cjs can drive it"
        )


class TestKioskWiring:
    def test_html_loads_the_helper_before_the_kiosk_script(self, kiosk_html):
        helper_at = kiosk_html.find("/shared/sse.js")
        script_at = kiosk_html.find("/children/script.js")
        assert helper_at != -1, "index.html must load /shared/sse.js"
        assert helper_at < script_at, (
            "sse.js must be loaded before script.js — script.js calls it at "
            "DOMContentLoaded"
        )

    def test_no_bare_event_source_in_the_kiosk(self, kiosk_script):
        """Both kiosk streams must go through the reconnecting helper."""
        assert "new EventSource(" not in kiosk_script, (
            "a bare `new EventSource(...)` gives up permanently on a 502 — use "
            "createReconnectingEventSource so the kiosk survives a backend restart"
        )

    def test_both_kiosk_streams_use_the_helper(self, kiosk_script):
        assert kiosk_script.count("createReconnectingEventSource(") == 2, (
            "both /api/nfc/read (card taps) and /api/system/events (GPIO "
            "buttons) must reconnect — they die together on a restart"
        )

    def test_no_stale_claim_that_eventsource_self_heals(self, kiosk_script):
        assert "Auto-reconnect built into EventSource" not in kiosk_script, (
            "that comment documented the bug: EventSource only self-heals on a "
            "dropped connection, never on an HTTP error response"
        )


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
class TestNodeSuite:
    def test_reconnect_behaviour(self):
        """Run the behavioural reconnect suite."""
        subprocess.run(["node", "--test", "tests/js/*.test.cjs"], check=True)

    def test_helper_parses(self):
        subprocess.run(["node", "--check", str(SSE_HELPER)], check=True)

    def test_kiosk_script_parses(self):
        subprocess.run(["node", "--check", str(KIOSK_SCRIPT)], check=True)


class TestKioskAssetsAlwaysRevalidate:
    """The fix is useless if the kiosk never re-fetches the page that loads it.

    NoCacheStaticFiles dispatches on the request path's extension, so a
    directory request (`GET /children/`, served as index.html by html=True)
    matched no branch and went out with an ETag and no Cache-Control at all.
    Firefox then reused its cached index.html heuristically — indefinitely, in
    practice — so a new <script> tag never reached the screen even across a
    browser restart.
    """

    @staticmethod
    def _client():
        # No context manager: the lifespan is irrelevant to static mounts and
        # starting it here would claim the real NFC reader.
        from fastapi.testclient import TestClient

        from app.main import app

        return TestClient(app)

    @pytest.mark.parametrize(
        "url",
        [
            "/children/",
            "/children/index.html",
            "/children/script.js",
            "/children/styles.css",
            "/shared/sse.js",
        ],
    )
    def test_kiosk_asset_must_revalidate(self, url):
        response = self._client().get(url)
        assert response.status_code == 200, url
        assert "no-cache" in response.headers.get("Cache-Control", ""), (
            f"{url} went out without a no-cache Cache-Control — the unattended "
            "kiosk will keep serving the stale copy after a deploy"
        )
