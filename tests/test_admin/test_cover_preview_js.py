"""Source-assertion tests for the cover preview in the /admin edit form.

When a story is put into edit mode, the cover field must show the already
uploaded image (served from /static/stories/<id>/<cover_image>) or an inline
SVG placeholder when the story has no cover. The wrap uses the `hidden` class
while the inner img/placeholder alternate via the `hidden` attribute, mirroring
the sticker modal pattern. A regression guard keeps the new code out of the
upload/remove-cover flow.
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


def _css_rule_block(text, selector):
    """Return the brace-matched block of the first rule for `selector`."""
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


class TestCoverPreviewHtml:
    def test_preview_wrap_exists_hidden_with_class(self, html_text):
        match = re.search(r'<div[^>]*id="cover-preview-wrap"[^>]*>', html_text)
        assert match, "missing <div id='cover-preview-wrap'>"
        wrap_tag = match.group(0)
        assert (
            "cover-preview-wrap" in wrap_tag
        ), "wrap must carry the cover-preview-wrap class"
        assert "hidden" in wrap_tag, "wrap must start hidden"

    def test_preview_img_exists_with_nonempty_alt(self, html_text):
        match = re.search(r'<img[^>]*id="cover-preview"[^>]*>', html_text)
        assert match, "missing <img id='cover-preview'>"
        assert re.search(
            r'alt="[^"]+"', match.group(0)
        ), "<img id='cover-preview'> must have a non-empty alt attribute"

    def test_placeholder_exists_with_inline_svg(self, html_text):
        assert (
            'id="cover-placeholder"' in html_text
        ), "missing <div id='cover-placeholder'>"
        assert re.search(
            r'<div[^>]*id="cover-placeholder"[^>]*>.*?<svg', html_text, re.DOTALL
        ), "cover-placeholder block must contain an inline <svg>"

    def test_preview_elements_live_inside_the_wrap(self, html_text):
        wrap_start = html_text.find('id="cover-preview-wrap"')
        assert wrap_start > 0, "missing <div id='cover-preview-wrap'>"
        wrap_end = html_text.find("</div>", wrap_start)
        assert wrap_end > wrap_start, "cover-preview-wrap div is never closed"
        wrap = html_text[wrap_start:wrap_end]
        assert 'id="cover-preview"' in wrap, "img must live inside the wrap"
        assert 'id="cover-placeholder"' in wrap, "placeholder must live inside the wrap"


class TestCoverPreviewJs:
    def test_show_cover_preview_defined(self, script_text):
        assert "function showCoverPreview(" in script_text

    def test_show_cover_placeholder_defined(self, script_text):
        assert "function showCoverPlaceholder(" in script_text

    def test_show_cover_preview_builds_static_url(self, script_text):
        body = _function_body(script_text, "function showCoverPreview(")
        assert (
            "'/static/stories/'" in body
        ), "showCoverPreview must build the /static/stories/ URL"
        assert "encodeURIComponent(" in body, "URL parts must be encoded"
        assert "+ '/' +" in body, "story id and cover file must be joined with '/'"

    def test_enter_edit_mode_shows_preview(self, script_text):
        body = _function_body(script_text, "function enterEditMode(")
        assert (
            "showCoverPreview(" in body
        ), "enterEditMode must call showCoverPreview(story)"

    def test_exit_edit_mode_hides_preview_wrap(self, script_text):
        body = _function_body(script_text, "function exitEditMode(")
        assert (
            "coverPreviewWrap" in body or "cover-preview-wrap" in body
        ), "exitEditMode must hide the cover preview wrap"

    def test_clear_cover_shows_placeholder(self, script_text):
        body = _function_body(script_text, "function clearCover(")
        assert (
            "showCoverPlaceholder(" in body
        ), "clearCover must show the placeholder (cover will be removed)"

    def test_new_functions_never_touch_upload_or_removal(self, script_text):
        for signature in (
            "function showCoverPreview(",
            "function showCoverPlaceholder(",
        ):
            body = _function_body(script_text, signature)
            for forbidden in ("removeCoverFlag", "FormData", "fetch("):
                assert forbidden not in body, (
                    f"{signature} must not reference {forbidden!r} "
                    "(preview code must not touch the upload/remove-cover flow)"
                )


class TestCoverPreviewCss:
    def test_cover_preview_wrap_rule_exists(self, css_text):
        _css_rule_block(css_text, ".cover-preview-wrap")

    def test_cover_preview_rule_exists(self, css_text):
        # Regex: a plain find of ".cover-preview" would match ".cover-preview-wrap"
        assert re.search(
            r"\.cover-preview\s*\{[^}]*max-width", css_text
        ), ".cover-preview rule must bound its width"

    def test_cover_placeholder_rule_exists(self, css_text):
        _css_rule_block(css_text, ".cover-placeholder")

    def test_cover_placeholder_svg_rule_exists(self, css_text):
        _css_rule_block(css_text, ".cover-placeholder svg")
