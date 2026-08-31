"""Emoji picker data for the /admin emoji pickers.

The emoji data lives only in static/admin/script.js: `emojiCategories`
(category -> list of emojis) and `emojiKeywords` (emoji -> search keywords).
All three pickers (emoji-picker, card-emoji-picker, promote-emoji-picker)
render their category tabs from the same objects, so the Lugares category
and the expanded Personajes list must exist in script.js and the new tabs
must be present in all three pickers' tab bars in index.html.

The literals are exercised for real: each object is extracted from
script.js by brace matching and evaluated under node.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT_PATH = Path("static/admin/script.js")
INDEX_PATH = Path("static/admin/index.html")

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');

function extractObject(marker) {
    const start = src.indexOf(marker);
    if (start === -1) throw new Error(marker + ' not found in script.js');
    const open = src.indexOf('{', start);
    let depth = 0, end = -1;
    for (let j = open; j < src.length; j++) {
        if (src[j] === '{') depth++;
        else if (src[j] === '}') { depth--; if (depth === 0) { end = j + 1; break; } }
    }
    if (end === -1) throw new Error('unbalanced braces in ' + marker);
    return eval('(' + src.slice(open, end) + ')');
}

const categories = extractObject('const emojiCategories = {');
const keywords = extractObject('const emojiKeywords = {');
console.log(JSON.stringify({categories, keywords}));
"""

PICKER_IDS = ("emoji-picker", "card-emoji-picker", "promote-emoji-picker")


pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node not installed"
)


@pytest.fixture(scope="module")
def emoji_data():
    """Evaluate the real emojiCategories/emojiKeywords literals via node."""
    harness = Path(__file__).with_name("_emoji_harness.js")
    harness.write_text(HARNESS, encoding="utf-8")
    try:
        result = subprocess.run(
            ["node", str(harness), str(SCRIPT_PATH)],
            capture_output=True,
            text=True,
            check=True,
        )
    finally:
        harness.unlink(missing_ok=True)
    return json.loads(result.stdout)


class TestLugaresCategory:
    def test_lugares_category_exists(self, emoji_data):
        categories = emoji_data["categories"]

        assert "Lugares" in categories
        lugares = categories["Lugares"]
        for emoji in ("🏰", "🏠", "🌌", "🏞️"):
            assert emoji in lugares, f"{emoji} missing from Lugares"
        assert len(lugares) >= 20, f"Lugares has {len(lugares)} emojis, need >= 20"


class TestPersonajesCategory:
    def test_personajes_category_has_characters(self, emoji_data):
        personajes = emoji_data["categories"]["Personajes"]

        for emoji in ("🧙", "🧚", "👸", "🤴", "🦸", "🧜", "🤖"):
            assert emoji in personajes, f"{emoji} missing from Personajes"
        assert (
            len(personajes) >= 40
        ), f"Personajes has {len(personajes)} emojis, need >= 40"

    def test_place_emojis_moved_out_of_personajes(self, emoji_data):
        personajes = emoji_data["categories"]["Personajes"]

        for emoji in ("🏰", "🏯", "🗼"):
            assert (
                emoji not in personajes
            ), f"{emoji} still in Personajes; it belongs in Lugares"


class TestDuplicates:
    def test_new_categories_have_no_duplicates(self, emoji_data):
        categories = emoji_data["categories"]

        for name in ("Lugares", "Personajes"):
            emojis = categories[name]
            assert len(set(emojis)) == len(emojis), (
                f"duplicates in {name}: "
                f"{[e for e in emojis if emojis.count(e) > 1]}"
            )


class TestPickerTabs:
    def test_all_pickers_expose_new_tabs(self):
        html = INDEX_PATH.read_text(encoding="utf-8")

        for picker_id in PICKER_IDS:
            start = html.index(f'id="{picker_id}"')
            end = html.index('class="emoji-grid"', start)
            block = html[start:end]
            for category in ("Lugares", "Personajes"):
                assert (
                    f'data-category="{category}"' in block
                ), f"{category} tab missing from {picker_id}"


class TestKeywords:
    def test_new_emojis_have_search_keywords(self, emoji_data):
        keywords = emoji_data["keywords"]

        for emoji in ("🏰", "🏠", "🌌", "🦸", "🧜"):
            assert emoji in keywords, f"no keywords entry for {emoji}"
            for kw in keywords[emoji]:
                assert kw == kw.lower(), f"keyword {kw!r} for {emoji} must be lowercase"
