"""Source-assertion tests for the /admin "Pegatina IA" modal on uploaded stories.

The sticker image lives in content/generated/<story_id>/ and is a separate
artifact from the story's own cover. These tests assert the modal markup, the
streaming generate/load flow in script.js, and a regression guard that the new
sticker code never touches the story cover (cover_image / remove_cover / #cover).
"""

import re
from pathlib import Path

import pytest

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


def _function_body(text, signature):
    """Return the brace-matched body of a function given its signature prefix."""
    start = text.find(signature)
    assert start > 0, f"{signature!r} not found in script.js"
    brace = text.find("{", start)
    assert brace > start, f"no body brace found for {signature!r}"
    depth = 1
    for i in range(brace + 1, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise AssertionError(f"unbalanced braces in {signature!r}")


def _sticker_block(text):
    """Text from `function openStickerModal(` through the end of `openPrintWindow`.

    This covers every function added for the sticker feature, so the regression
    guard can assert none of them touches the story cover.
    """
    start = text.find("function openStickerModal(")
    assert start > 0, "function openStickerModal( not found in script.js"
    print_start = text.find("function openPrintWindow(", start)
    assert (
        print_start > start
    ), "function openPrintWindow( not found after openStickerModal in script.js"
    brace = text.find("{", print_start)
    depth = 1
    for i in range(brace + 1, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise AssertionError("unbalanced braces in openPrintWindow")


def _css_rule_block(text, selector):
    """Return the brace-matched block of the first rule for `selector`.

    Works for plain rules (`.story-info`) and at-rules
    (`@media (min-width: 768px)`); the block is delimited at its closing
    brace so nested braces inside the rule body are handled.
    """
    start = text.find(selector)
    assert start >= 0, f"{selector!r} not found in styles.css"
    brace = text.find("{", start)
    assert brace > start, f"no body brace found for {selector!r}"
    depth = 1
    for i in range(brace + 1, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise AssertionError(f"unbalanced braces in {selector!r}")


class TestStickerModalHtml:
    def test_modal_overlay_exists(self, html_text):
        assert '<div id="sticker-modal" class="modal-overlay" hidden>' in html_text

    def test_hint_input_with_maxlength(self, html_text):
        assert re.search(
            r'<input[^>]*id="sticker-hint"[^>]*maxlength="200"', html_text
        ), "missing <input id='sticker-hint' maxlength='200'>"
        assert re.search(
            r'<input[^>]*type="text"[^>]*id="sticker-hint"', html_text
        ), "sticker-hint input must be type='text'"

    def test_action_buttons_exist(self, html_text):
        for element_id in ("sticker-generate", "sticker-print", "sticker-close"):
            assert f'id="{element_id}"' in html_text, f"missing id={element_id!r}"

    def test_preview_img_and_status_exist(self, html_text):
        assert re.search(
            r'<img[^>]*id="sticker-preview"', html_text
        ), "missing <img id='sticker-preview'>"
        assert 'id="sticker-status"' in html_text, "missing id='sticker-status'"

    def test_note_clares_image_is_not_the_cover(self, html_text):
        assert (
            "no sustituye" in html_text
        ), "modal must state the sticker image does not replace the story cover"


class TestStickerJs:
    def test_open_sticker_modal_defined(self, script_text):
        assert "function openStickerModal(" in script_text

    def test_close_sticker_modal_defined(self, script_text):
        assert "function closeStickerModal(" in script_text

    def test_generate_sticker_defined(self, script_text):
        assert "async function generateSticker(" in script_text

    def test_load_existing_sticker_defined(self, script_text):
        assert "async function loadExistingSticker(" in script_text

    def test_open_print_window_defined(self, script_text):
        assert "function openPrintWindow(" in script_text

    def test_story_card_button_gated_by_ai_enabled(self, script_text):
        body = _function_body(script_text, "function createStoryCard(")
        assert "Pegatina IA" in body, "createStoryCard must add a 'Pegatina IA' button"
        assert (
            "window.aiEnabled" in body
        ), "the 'Pegatina IA' button must be gated by window.aiEnabled"

    def test_get_sticker_fetch(self, script_text):
        assert re.search(
            r"fetch\(\s*'/api/stories/'\s*\+\s*encodeURIComponent\(", script_text
        ), "missing GET fetch('/api/stories/' + encodeURIComponent(...))"
        assert re.search(
            r"\)\s*\+\s*'/sticker'\s*\)", script_text
        ), "missing '... + \"/sticker\")' fetch suffix"

    def test_post_sticker_fetch(self, script_text):
        post_match = re.search(
            r"fetch\(\s*'/api/stories/'\s*\+\s*encodeURIComponent\([^)]*\)\s*\+\s*'/sticker'\s*,\s*\{",
            script_text,
        )
        assert post_match, "missing POST fetch to /api/stories/<id>/sticker"
        options = script_text[post_match.end() :]
        assert re.search(
            r"method:\s*'POST'", options
        ), "sticker fetch must use method 'POST'"

    def test_stream_event_keys_parsed(self, script_text):
        block = _sticker_block(script_text)
        for key in ("sticker_started", "sticker_ready", "sticker_failed"):
            assert key in block, f"sticker stream code does not handle {key!r}"

    def test_new_functions_never_touch_the_cover(self, script_text):
        block = _sticker_block(script_text)
        for forbidden in ("remove_cover", "cover_image", "getElementById('cover')"):
            assert forbidden not in block, (
                f"sticker functions must not reference {forbidden!r} "
                "(the sticker is separate from the story cover)"
            )

    def test_open_print_preview_delegates_to_open_print_window(self, script_text):
        body = _function_body(script_text, "function openPrintPreview(")
        assert (
            "openPrintWindow(" in body
        ), "openPrintPreview must delegate to openPrintWindow"
        assert (
            "window.open" not in body
        ), "openPrintPreview must not build the print window itself anymore"


class TestStickerCss:
    def test_sticker_modal_rule_exists(self, css_text):
        assert ".sticker-modal" in css_text, "styles.css missing .sticker-modal rule"

    def test_sticker_preview_rule_exists(self, css_text):
        assert re.search(
            r"#sticker-preview\s*\{", css_text
        ), "styles.css missing #sticker-preview rule"


class TestStickerPlaceholder:
    """The modal must show a placeholder until an image exists."""

    def test_placeholder_block_exists_with_inline_svg(self, html_text):
        assert (
            'id="sticker-placeholder"' in html_text
        ), "missing <div id='sticker-placeholder'>"
        assert re.search(
            r'<div[^>]*id="sticker-placeholder"[^>]*>.*?<svg', html_text, re.DOTALL
        ), "sticker-placeholder block must contain an inline <svg>"

    def test_preview_img_starts_hidden(self, html_text):
        assert re.search(
            r'<img[^>]*id="sticker-preview"[^>]*\bhidden\b', html_text
        ), "<img id='sticker-preview'> must carry the hidden attribute"

    def test_preview_wrap_no_longer_hidden(self, html_text):
        match = re.search(r'<div[^>]*id="sticker-preview-wrap"[^>]*>', html_text)
        assert match, "missing <div id='sticker-preview-wrap'>"
        assert "hidden" not in match.group(
            0
        ), "sticker-preview-wrap must no longer carry the hidden attribute"

    def test_show_sticker_placeholder_defined(self, script_text):
        assert "function showStickerPlaceholder(" in script_text

    def test_load_existing_sticker_shows_placeholder_on_missing(self, script_text):
        body = _function_body(script_text, "async function loadExistingSticker(")
        assert (
            "showStickerPlaceholder(" in body
        ), "loadExistingSticker must show the placeholder when no sticker exists"

    def test_open_sticker_modal_shows_placeholder(self, script_text):
        body = _function_body(script_text, "function openStickerModal(")
        assert (
            "showStickerPlaceholder(" in body
        ), "openStickerModal must start the modal showing the placeholder"

    def test_show_sticker_image_toggles_preview_and_placeholder(self, script_text):
        body = _function_body(script_text, "function showStickerImage(")
        assert (
            "sticker-preview" in body
        ), "showStickerImage must reveal #sticker-preview"
        assert (
            "sticker-placeholder" in body
        ), "showStickerImage must hide #sticker-placeholder"

    def test_sticker_placeholder_css_rule_exists(self, css_text):
        block = _css_rule_block(css_text, ".sticker-placeholder")
        assert (
            "text-align: center" in block
        ), ".sticker-placeholder rule must center its content"


class TestStoryCardLayout:
    """The fourth action button must not crush the card info column.

    Regression guard for the 'Pegatina IA' button: with four actions the
    desktop row no longer fits the 600px container, so the actions must be
    laid out in a fixed-width 2x2 grid and the info column needs a
    min-width floor.
    """

    def test_story_info_has_rem_min_width_floor(self, css_text):
        block = _css_rule_block(css_text, ".story-info")
        assert (
            "min-width: 0" not in block
        ), ".story-info must not keep min-width: 0 (lets the column collapse)"
        assert re.search(
            r"min-width:\s*\d+(\.\d+)?rem", block
        ), ".story-info needs a rem min-width floor"

    def test_desktop_story_actions_use_grid(self, css_text):
        media = _css_rule_block(css_text, "@media (min-width: 768px)")
        block = _css_rule_block(media, ".story-actions")
        assert "display: grid" in block, "desktop .story-actions must use a grid layout"

    def test_desktop_story_actions_grid_two_columns(self, css_text):
        media = _css_rule_block(css_text, "@media (min-width: 768px)")
        block = _css_rule_block(media, ".story-actions")
        assert (
            "grid-template-columns: repeat(2, 1fr)" in block
        ), "desktop .story-actions must lay the four buttons out in two columns"

    def test_desktop_story_actions_buttons_are_content_sized(self, css_text):
        media = _css_rule_block(css_text, "@media (min-width: 768px)")
        block = _css_rule_block(media, ".story-actions .btn")
        assert (
            "width: auto" in block
        ), "desktop .story-actions .btn must override the base .btn width: 100%"

    def test_base_story_actions_stay_column(self, css_text):
        block = _css_rule_block(css_text, ".story-actions")
        assert (
            "flex-direction: column" in block
        ), "mobile .story-actions layout (column) must not change"
