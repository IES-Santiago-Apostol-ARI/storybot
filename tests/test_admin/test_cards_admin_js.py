"""renderCardList behavior for the /admin "Tarjetas de Parámetros" list.

loadCards() fetches GET /api/cards without a type filter, so the payload also
contains story-type cards (one per story with an NFC assigned). The section only
knows how to render 'parameter' and 'go' cards, so story cards must be skipped
entirely — not appended as empty .card-item boxes.

renderCardList is exercised for real: the function body is extracted from
script.js and run under node against a minimal DOM stub.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT_PATH = Path("static/admin/script.js")

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');

// Extract `function renderCardList(cards) { ... }` by brace matching.
const start = src.indexOf('function renderCardList');
if (start === -1) throw new Error('renderCardList not found in script.js');
let depth = 0, end = -1;
for (let j = src.indexOf('{', start); j < src.length; j++) {
    if (src[j] === '{') depth++;
    else if (src[j] === '}') { depth--; if (depth === 0) { end = j + 1; break; } }
}
if (end === -1) throw new Error('unbalanced braces in renderCardList');
const fnSrc = src.slice(start, end);

function makeEl(tag) {
    return {
        tagName: tag,
        className: '',
        textContent: '',
        children: [],
        style: { cssText: '' },
        onclick: null,
        set innerHTML(v) { this._innerHTML = v; this.children = []; },
        get innerHTML() { return this._innerHTML || ''; },
        appendChild(child) { this.children.push(child); return child; },
    };
}

const container = makeEl('div');
const document = {
    createElement: makeEl,
    getElementById: (id) => (id === 'card-list' ? container : null),
};
function deleteCard() {}

const renderCardList = eval('(' + fnSrc + ')');
renderCardList(JSON.parse(process.argv[3]));

const dump = (el) => ({
    className: el.className,
    textContent: el.textContent,
    children: el.children.map(dump),
});

console.log(JSON.stringify({
    innerHTML: container.innerHTML,
    items: container.children.map(dump),
}));
"""

PARAMETER_CARD = {
    "uid": "04:38:9C:92",
    "type": "parameter",
    "category": "personaje",
    "value": "buho",
    "emoji": "🦉",
    "label": "buho",
}
GO_CARD = {"uid": "27:CB:B9:7A", "type": "go"}
STORY_CARD = {"uid": "C6:97:D7:BD", "type": "story", "story_id": "abc-123"}


pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node not installed"
)


def render(tmp_path, cards):
    """Run renderCardList(cards) under node and return the rendered container."""
    harness = tmp_path / "render_card_list.js"
    harness.write_text(HARNESS, encoding="utf-8")
    result = subprocess.run(
        ["node", str(harness), str(SCRIPT_PATH), json.dumps(cards)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


class TestRenderCardList:
    def test_story_cards_are_skipped(self, tmp_path):
        """Story cards must not produce empty .card-item boxes."""
        out = render(tmp_path, [PARAMETER_CARD, STORY_CARD, GO_CARD, STORY_CARD])

        assert len(out["items"]) == 2, (
            "only the parameter and go cards should be rendered; story cards "
            f"must be skipped, got {len(out['items'])} items"
        )
        for item in out["items"]:
            assert item["children"], "rendered card must not be empty"

    def test_only_story_cards_shows_empty_state(self, tmp_path):
        """A list of nothing but story cards is an empty parameter list."""
        out = render(tmp_path, [STORY_CARD, STORY_CARD])

        assert out["items"] == []
        assert "empty-state" in out["innerHTML"]

    def test_parameter_and_go_cards_still_render(self, tmp_path):
        """The skip must not regress the two types the section does render."""
        out = render(tmp_path, [PARAMETER_CARD, GO_CARD])

        assert len(out["items"]) == 2
        assert out["items"][0]["className"] == "card-item"
        assert out["items"][1]["className"] == "card-item card-item--go"

    def test_empty_payload_shows_empty_state(self, tmp_path):
        out = render(tmp_path, [])

        assert out["items"] == []
        assert "empty-state" in out["innerHTML"]
