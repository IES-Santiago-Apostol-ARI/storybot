"""Kiosk parameter-card toggle source-assertion tests.

Tapping a parameter card a second time (same uid) must remove its chip
from the collection instead of pushing a duplicate. The file also covers
the reset performed when playing a pre-recorded story.
"""

import re
from pathlib import Path

import pytest

SCRIPT_PATH = Path("static/children/script.js")


@pytest.fixture(scope="module")
def script_text():
    """Read the kiosk script once per module."""
    return SCRIPT_PATH.read_text(encoding="utf-8")


def _balanced_body(text, header):
    """Return the brace-balanced body of the block opened by ``header``."""
    start = text.find(header)
    assert start != -1, f"Branch header not found: {header!r}"
    brace = text.find("{", start)
    assert brace != -1, f"No opening brace after header: {header!r}"
    depth = 1
    end = brace + 1
    while depth > 0 and end < len(text):
        if text[end] == "{":
            depth += 1
        elif text[end] == "}":
            depth -= 1
        end += 1
    assert depth == 0, f"Unbalanced braces for header: {header!r}"
    return text[brace + 1 : end - 1]


@pytest.fixture(scope="module")
def param_branch(script_text):
    """Body of the `if (card_type === 'parameter') {` branch."""
    return _balanced_body(script_text, "if (card_type === 'parameter') {")


@pytest.fixture(scope="module")
def play_story(script_text):
    """Body of `function playStory(story) {`."""
    return _balanced_body(script_text, "function playStory(story) {")


class TestKioskParamToggle:
    """Source-assertion tests for the parameter-card toggle branch.

    The branch must identify the tapped card by uid: a second tap on the
    same card removes its chip (and returns to idle when the collection
    empties) instead of pushing a duplicate.
    """

    def test_collected_param_stores_its_uid(self, param_branch):
        """The object pushed into collectingParams carries the card uid."""
        assert re.search(
            r"collectingParams\.push\(\s*\{[^}]*\buid\b", param_branch
        ), "Pushed param object must include a 'uid' property"

    def test_branch_looks_up_the_uid_before_pushing(self, param_branch):
        """A uid lookup over collectingParams precedes collectingParams.push."""
        lookup = re.search(r"collectingParams\.findIndex\([^)]*p\.uid", param_branch)
        assert lookup, "Missing collectingParams.findIndex lookup by p.uid"
        push_idx = param_branch.find("collectingParams.push")
        assert push_idx != -1, "collectingParams.push not found in branch"
        assert lookup.start() < push_idx, (
            f"uid lookup at {lookup.start()} must precede "
            f"collectingParams.push at {push_idx}"
        )

    def test_branch_removes_the_matching_chip(self, param_branch):
        """The branch removes the found element via collectingParams.splice."""
        assert (
            "collectingParams.splice(" in param_branch
        ), "Missing collectingParams.splice( removal in parameter branch"

    def test_push_is_not_unconditional(self, param_branch):
        """push happens once and is unreachable when the uid was already in."""
        assert (
            param_branch.count("collectingParams.push") == 1
        ), "collectingParams.push must appear exactly once in the branch"
        splice_idx = param_branch.find("collectingParams.splice(")
        assert splice_idx != -1, "collectingParams.splice( not found in branch"
        push_idx = param_branch.find("collectingParams.push")
        between = param_branch[splice_idx:push_idx]
        assert "return" in between or "else" in between, (
            "push must not be reachable when the uid was already collected "
            "(expected a return or else between splice and push)"
        )

    def test_emptying_the_collection_returns_to_idle(self, param_branch):
        """Emptying the collection clears the display and returns to IDLE."""
        empty_header = "if (collectingParams.length === 0) {"
        assert (
            empty_header in param_branch
        ), "Missing empty-collection check in parameter branch"
        empty_body = _balanced_body(param_branch, empty_header)
        assert (
            "clearParameterDisplay()" in empty_body
        ), "Empty-collection case must call clearParameterDisplay()"
        assert (
            "transitionTo(STATES.IDLE)" in empty_body
        ), "Empty-collection case must call transitionTo(STATES.IDLE)"

    def test_other_card_branches_untouched(self, script_text):
        """Regression: go/story/unknown branches contain no splice()."""
        for header in (
            "if (card_type === 'go') {",
            "if (card_type === 'story') {",
            "if (card_type === 'unknown') {",
        ):
            body = _balanced_body(script_text, header)
            assert "splice(" not in body, f"Branch {header!r} must not contain splice("


class TestStoryCancelsParameterCollection:
    """A pre-recorded story cancels an in-progress parameter collection.

    Playing a stored story while COLLECTING must reset the collection and
    return to IDLE before the idle guard, so the story actually plays
    instead of the tap being swallowed.
    """

    def test_play_story_leaves_collecting_before_the_idle_guard(self, play_story):
        """The COLLECTING reset precedes the idle guard in playStory."""
        collecting_header = "if (currentState === STATES.COLLECTING) {"
        assert (
            collecting_header in play_story
        ), "playStory must handle the COLLECTING state"
        collecting_body = _balanced_body(play_story, collecting_header)
        transition_idx = collecting_body.find("transitionTo(STATES.IDLE)")
        assert (
            transition_idx != -1
        ), "COLLECTING case must call transitionTo(STATES.IDLE)"
        guard_idx = play_story.find("if (currentState !== STATES.IDLE) return;")
        assert guard_idx != -1, "Idle guard missing from playStory"
        collecting_idx = play_story.find(collecting_header)
        assert collecting_idx < guard_idx, (
            f"COLLECTING reset at {collecting_idx} must precede the idle "
            f"guard at {guard_idx}"
        )

    def test_play_story_clears_the_parameter_chips(self, play_story):
        """playStory calls clearParameterDisplay()."""
        assert (
            "clearParameterDisplay()" in play_story
        ), "playStory must call clearParameterDisplay()"

    def test_play_story_drops_the_preserved_generation_params(self, play_story):
        """playStory resets lastGenerationParams so D-09 cannot restore chips."""
        assert (
            "lastGenerationParams = []" in play_story
        ), "playStory must set lastGenerationParams = []"

    def test_idle_guard_survives(self, play_story):
        """The idle guard is still present (protects taps during PLAYING)."""
        assert (
            "if (currentState !== STATES.IDLE) return;" in play_story
        ), "Idle guard must remain in playStory"

    def test_nfc_story_branch_still_resets(self, script_text):
        """Regression: the NFC story branch still performs its reset."""
        body = _balanced_body(script_text, "if (card_type === 'story') {")
        assert (
            "clearParameterDisplay()" in body
        ), "NFC story branch must call clearParameterDisplay()"
        assert (
            "lastGenerationParams = []" in body
        ), "NFC story branch must reset lastGenerationParams"
