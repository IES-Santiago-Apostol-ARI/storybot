"""API-03 regression sweep: parity across non-AI endpoints for both lifespan branches.

Requirement API-03: "All other endpoints work identically regardless of AI capability."
Tests each non-AI route under STORYBOT_AI=1 and STORYBOT_AI=0 for equal status codes.
"""

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import State


def _reset_app_state(app):
    """Clear app.state so attributes from a prior TestClient session don't leak.

    Starlette's State object is backed by a dict on the app instance; exiting a
    TestClient context manager only triggers lifespan shutdown, not a state wipe.
    Without this reset, attributes set by an earlier test (e.g. story_generator)
    persist and cause false negatives in the "NOT set" tests.
    """
    app.state = State()


@pytest.fixture
def lifespan_env_ai_on(tmp_path, monkeypatch):
    """Lifespan env with AI forced ON (STORYBOT_AI=1), TESTING deleted.

    Disables TESTING so the full lifespan body runs (TTSPipeline wiring,
    content dir bootstrap). Overrides GENERATED_DIR to tmp so the sweeper
    does not touch the real filesystem.
    """
    generated = tmp_path / "generated"
    generated.mkdir()
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.setenv("STORYBOT_AI", "1")
    monkeypatch.setenv("STORYBOT_LIFESPAN_TEST", "1")
    from app.services.story_manager import StoryManager

    monkeypatch.setattr(StoryManager, "GENERATED_DIR", generated)
    return generated


@pytest.fixture
def lifespan_env_ai_off(tmp_path, monkeypatch):
    """Lifespan env with AI forced OFF (STORYBOT_AI=0), TESTING deleted."""
    generated = tmp_path / "generated"
    generated.mkdir()
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.setenv("STORYBOT_AI", "0")
    monkeypatch.setenv("STORYBOT_LIFESPAN_TEST", "1")
    from app.services.story_manager import StoryManager

    monkeypatch.setattr(StoryManager, "GENERATED_DIR", generated)
    return generated


# Non-AI routes covered by API-03 (excludes /api/capabilities and /api/generate/story)
NON_AI_ROUTES = [
    ("GET", "/api/stories"),
    ("GET", "/api/nfc/status"),
    ("GET", "/api/system/status"),
    ("GET", "/api/cards"),
    ("GET", "/api/generated"),
    ("POST", "/api/printer/print"),
]


@pytest.fixture(scope="module")
def branch_statuses(tmp_path_factory):
    """Status codes for every NON_AI_ROUTE under both lifespan branches.

    One TestClient (= one full lifespan startup) per branch for the whole
    module instead of two per parametrized route — 12 lifespans -> 2
    (IMPROVEMENTS.md §6 suite-speed note). Parity is a property of the
    lifespan branch, not of per-test isolation, so sharing the client per
    branch does not weaken the assertion.
    """
    from app.main import app
    from app.services.story_manager import StoryManager

    statuses: dict[tuple[str, str], dict[str, int]] = {
        route: {} for route in NON_AI_ROUTES
    }
    mp = pytest.MonkeyPatch()
    try:
        for ai_value in ("1", "0"):
            mp.delenv("TESTING", raising=False)
            mp.setenv("STORYBOT_AI", ai_value)
            mp.setenv("STORYBOT_LIFESPAN_TEST", "1")

            # Separate tmp dirs for each branch to avoid collision
            generated = tmp_path_factory.mktemp(f"generated_{ai_value}")
            mp.setattr(StoryManager, "GENERATED_DIR", generated)

            _reset_app_state(app)
            with TestClient(app) as client:
                for method, url in NON_AI_ROUTES:
                    statuses[(method, url)][ai_value] = client.request(
                        method, url
                    ).status_code
    finally:
        mp.undo()
    return statuses


@pytest.mark.parametrize("method,url", NON_AI_ROUTES)
def test_non_ai_routes_behave_identically(method: str, url: str, branch_statuses):
    """Assert each non-AI route returns the same status under both lifespan branches.

    API-03 contract: parity, not a specific status code. If a route returns 200
    with AI on, it must return 200 with AI off. If it returns 422 with AI on,
    it must return 422 with AI off.
    """
    on_status = branch_statuses[(method, url)]["1"]
    off_status = branch_statuses[(method, url)]["0"]

    assert on_status == off_status, (
        f"API-03: {method} {url} returned {on_status} with AI on and "
        f"{off_status} with AI off — must match"
    )
