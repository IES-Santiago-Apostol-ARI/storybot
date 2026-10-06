"""Tests for the Spanish -> English cover translation (rules + llama-server).

The network is never used: llama-server answers come from httpx.MockTransport.
"""

import json
from random import Random

import httpx
import pytest

from app.services import cover_llm_translator, cover_prompt_builder
from app.services.cover_translator import translate, translate_with_coverage


class TestVocabulary:
    @pytest.mark.parametrize(
        ("spanish", "english"),
        [
            ("paloma", "dove"),
            ("hada", "fairy"),
            ("bruja", "witch"),
            ("mago", "wizard"),
            ("unicornio", "unicorn"),
            ("sirena", "mermaid"),
            ("pirata", "pirate"),
            ("astronauta", "astronaut"),
            ("niña", "girl"),
            ("niño", "boy"),
            ("selva", "jungle"),
            ("globo", "balloon"),
            ("Dragón", "dragon"),
        ],
    )
    def test_story_words_are_known(self, spanish, english):
        assert translate_with_coverage(spanish) == (english, True)


class TestInflection:
    @pytest.mark.parametrize(
        ("spanish", "english"),
        [
            ("gata", "cat"),
            ("leona", "lion"),
            ("perros", "dogs"),
            ("flores", "flowers"),
            ("peces", "fish"),
            ("ratones", "mice"),
            ("nubes", "clouds"),
            ("mariposas", "butterflies"),
            ("pequeña", "small"),
            ("asustadas", "scared"),
            ("felices", "happy"),
            ("conejito", "little rabbit"),
            ("leoncito", "little lion"),
            ("florecita", "little flower"),
            ("estrellita", "little star"),
            ("tres cerditos", "three little pigs"),
        ],
    )
    def test_gender_number_and_diminutive(self, spanish, english):
        assert translate(spanish) == english

    def test_explicit_feminine_wins_over_the_masculine_fallback(self):
        assert translate("abuela") == "grandmother"
        assert translate("reina") == "queen"


class TestConnectors:
    def test_y_becomes_and(self):
        assert translate("un perro y un gato") == "dog and cat"

    def test_con_becomes_with(self):
        assert translate("un oso con un sombrero") == "bear with hat"

    def test_de_becomes_of(self):
        assert translate("castillo de hielo") == "castle of ice"

    def test_articles_are_dropped(self):
        assert translate("una paloma") == "dove"

    def test_leading_connector_is_dropped(self):
        assert translate("con miedo") == "scared"

    @pytest.mark.parametrize("value", ["el", "y", "la de", ""])
    def test_nothing_drawable_gives_empty(self, value):
        assert translate_with_coverage(value) == ("", True)


class TestWordOrder:
    @pytest.mark.parametrize(
        ("spanish", "english"),
        [
            ("gato negro", "black cat"),
            ("oso polar", "polar bear"),
            ("un castillo grande", "big castle"),
            ("gato negro y blanco", "black and white cat"),
            ("pequeño dragón verde", "small green dragon"),
            ("princesa valiente y un dragón", "brave princess and dragon"),
            ("muy feliz", "very happy"),
        ],
    )
    def test_adjectives_move_before_the_noun(self, spanish, english):
        assert translate(spanish) == english


class TestAmbiguousWords:
    def test_rosa_alone_is_the_flower(self):
        assert translate("rosa") == "rose"
        assert translate("una rosa roja") == "red rose"

    def test_rosa_after_a_noun_is_the_colour(self):
        assert translate("vestido rosa") == "pink dress"


class TestPhrases:
    @pytest.mark.parametrize(
        ("spanish", "english"),
        [
            ("caballito de mar", "seahorse"),
            ("pez payaso", "clownfish"),
            ("la casa del árbol", "treehouse"),
            ("varita mágica", "magic wand"),
        ],
    )
    def test_fixed_expressions(self, spanish, english):
        assert translate(spanish) == english


class TestUnknownWords:
    def test_pass_through_and_are_reported(self):
        assert translate_with_coverage("zorp") == ("zorp", False)

    def test_still_take_their_adjective(self):
        assert translate_with_coverage("zorp azul") == ("blue zorp", False)


def _llama(content: str, seen: list | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": content}}]}
        )

    return httpx.MockTransport(handler)


class TestLlamaTranslator:
    async def test_numbered_answers_map_back_in_order(self):
        seen: list = []
        out = await cover_llm_translator.translate_values(
            ["un erizo con casco", "el farolillo"],
            transport=_llama("1. hedgehog with helmet\n2. little lantern", seen),
        )
        assert out == ["hedgehog with helmet", "little lantern"]
        assert seen[0]["messages"][1]["content"] == (
            "1. un erizo con casco\n2. el farolillo"
        )
        assert seen[0]["stream"] is False

    async def test_think_block_and_decoration_are_stripped(self):
        out = await cover_llm_translator.translate_values(
            ["farolillo"],
            transport=_llama('<think>\n\n</think>\n\n1) "Little Lantern."'),
        )
        assert out == ["little lantern"]

    async def test_long_answer_is_capped(self):
        out = await cover_llm_translator.translate_values(
            ["x"], transport=_llama("1. " + " ".join(["word"] * 30))
        )
        assert len(out[0].split()) == cover_llm_translator.MAX_WORDS

    async def test_missing_or_unusable_lines_are_none(self):
        out = await cover_llm_translator.translate_values(
            ["a", "b", "c"], transport=_llama("1. apple\n3. ¡¡¡")
        )
        assert out == ["apple", None, None]

    async def test_blank_values_are_not_sent(self):
        seen: list = []
        out = await cover_llm_translator.translate_values(
            ["", "farolillo"], transport=_llama("1. lantern", seen)
        )
        assert out == [None, "lantern"]
        assert seen[0]["messages"][1]["content"] == "1. farolillo"

    async def test_server_error_degrades_to_none(self):
        transport = httpx.MockTransport(lambda request: httpx.Response(503))
        assert await cover_llm_translator.translate_values(
            ["farolillo"], transport=transport
        ) == [None]

    async def test_connection_failure_degrades_to_none(self):
        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("llama-server is down")

        assert await cover_llm_translator.translate_values(
            ["farolillo"], transport=httpx.MockTransport(refuse)
        ) == [None]

    async def test_malformed_response_degrades_to_none(self):
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"unexpected": True})
        )
        assert await cover_llm_translator.translate_values(
            ["farolillo"], transport=transport
        ) == [None]

    async def test_suite_never_reaches_a_real_server(self):
        """Without a transport, TESTING short-circuits before any request."""
        assert await cover_llm_translator.translate_values(["farolillo"]) == [None]


class TestHybridBuild:
    """build_translated: rules first, llama-server only for unknown words."""

    @staticmethod
    def _spy(monkeypatch, answers):
        calls: list = []

        async def fake(values, **kwargs):
            calls.append(values)
            return answers

        monkeypatch.setattr(cover_llm_translator, "translate_values", fake)
        return calls

    async def test_known_values_never_ask_llama(self, monkeypatch):
        calls = self._spy(monkeypatch, [])
        positive, _ = await cover_prompt_builder.build_translated(
            [
                {"category": "personaje", "value": "un gato negro"},
                {"category": "lugar", "value": "castillo"},
            ],
            rng=Random(0),
        )
        assert calls == []
        assert "cute cartoon black cat" in positive
        assert "in a simple castle" in positive

    async def test_only_values_with_unknown_words_are_sent(self, monkeypatch):
        calls = self._spy(monkeypatch, ["hedgehog with helmet"])
        positive, _ = await cover_prompt_builder.build_translated(
            [
                {"category": "personaje", "value": "un erizo con casco"},
                {"category": "lugar", "value": "bosque"},
            ],
            rng=Random(0),
        )
        assert calls == [["un erizo con casco"]]
        assert "cute cartoon hedgehog with helmet" in positive
        assert "in a simple forest" in positive

    async def test_falls_back_to_the_rules_when_llama_has_no_answer(self, monkeypatch):
        self._spy(monkeypatch, [None])
        positive, _ = await cover_prompt_builder.build_translated(
            [{"category": "personaje", "value": "un erizo con casco"}],
            rng=Random(0),
        )
        assert "cute cartoon hedgehog with casco" in positive

    async def test_english_answer_is_not_translated_again(self, monkeypatch):
        """ "pan" is bread in Spanish; llama's English must be left alone."""
        self._spy(monkeypatch, ["frying pan"])
        positive, _ = await cover_prompt_builder.build_translated(
            [{"category": "personaje", "value": "sartencita"}], rng=Random(0)
        )
        assert "cute cartoon frying pan" in positive

    async def test_no_params_gives_the_plain_style_prompt(self, monkeypatch):
        calls = self._spy(monkeypatch, [])
        positive, _ = await cover_prompt_builder.build_translated([])
        assert calls == []
        assert positive == cover_prompt_builder.STYLE_PREAMBLE
