"""Tests for cover_prompt_builder — AC-1."""

from random import Random
from unittest.mock import patch

from app.services.cover_prompt_builder import (
    COMPOSITION_VARIANTS,
    MAX_CHARACTERS,
    MAX_CLIP_TOKENS,
    NEGATIVE_PROMPT,
    POSE_VARIANTS,
    STYLE_HEAD,
    STYLE_PREAMBLE,
    STYLE_TAIL,
    build,
)


def _params(*specs: tuple[str, str]) -> list[dict]:
    return [{"category": cat, "value": val} for cat, val in specs]


def _composition_of(positive: str) -> str:
    """The framing slot the prompt was built with (between head and tail)."""
    return positive[
        positive.index(STYLE_HEAD) + len(STYLE_HEAD) : positive.index(f", {STYLE_TAIL}")
    ]


def _over_budget_while(*phrases: str):
    """Fake token counter: over budget while any phrase is still present.

    Content-aware instead of a fixed side_effect list, so the assertions stay
    valid as reduction steps are added to the ladder.
    """

    def count(text: str) -> int:
        return MAX_CLIP_TOKENS + 1 if any(p in text for p in phrases) else 1

    return count


class TestStylePreamble:
    def test_subject_leads_then_preamble(self):
        positive, _ = build(_params(("personaje", "robot")))
        assert positive.startswith("cute cartoon robot")
        assert STYLE_HEAD in positive
        assert STYLE_TAIL in positive
        assert positive.index("cute cartoon robot") < positive.index(STYLE_HEAD)

    def test_negative_is_verbatim(self):
        _, negative = build(_params(("personaje", "robot")))
        assert negative == NEGATIVE_PROMPT

    def test_empty_params_returns_preamble_only(self):
        positive, negative = build([])
        assert positive == STYLE_PREAMBLE
        assert negative == NEGATIVE_PROMPT


class TestSubstitutionPatterns:
    def test_personaje_gets_cute_cartoon_prefix(self):
        positive, _ = build(_params(("personaje", "robot")))
        assert "cute cartoon robot" in positive

    def test_lugar_gets_simple_prefix(self):
        positive, _ = build(_params(("personaje", "robot"), ("lugar", "garden")))
        assert "in a simple garden" in positive

    def test_objeto_gets_holding_prefix(self):
        positive, _ = build(_params(("personaje", "robot"), ("objeto", "flower")))
        assert "holding/with a simple flower" in positive

    def test_emocion_gets_looking_prefix(self):
        positive, _ = build(_params(("personaje", "robot"), ("emoción", "happy")))
        assert "looking happy" in positive

    def test_problema_is_skipped(self):
        positive, _ = build(_params(("personaje", "robot"), ("problema", "fear")))
        assert "fear" not in positive
        # Only personaje phrase should be present
        assert "cute cartoon robot" in positive


class TestTokenBudgetEnforcement:
    """Reduction ladder: lugar → objeto → emoción → pose → extra characters.
    The leading character is never dropped."""

    _ALL = (
        ("personaje", "robot"),
        ("lugar", "garden"),
        ("objeto", "flower"),
        ("emoción", "happy"),
    )

    @patch("app.services.cover_prompt_builder._count_tokens")
    def test_drops_lugar_first(self, mock_count):
        mock_count.side_effect = _over_budget_while("in a simple garden")
        positive, _ = build(_params(*self._ALL), rng=Random(0))
        assert "in a simple garden" not in positive
        assert "cute cartoon robot" in positive
        assert "holding/with a simple flower" in positive
        assert "looking happy" in positive

    @patch("app.services.cover_prompt_builder._count_tokens")
    def test_drops_objeto_second(self, mock_count):
        mock_count.side_effect = _over_budget_while(
            "in a simple garden", "holding/with a simple flower"
        )
        positive, _ = build(_params(*self._ALL), rng=Random(0))
        assert "in a simple garden" not in positive
        assert "holding/with a simple flower" not in positive
        assert "cute cartoon robot" in positive
        assert "looking happy" in positive

    @patch("app.services.cover_prompt_builder._count_tokens")
    def test_drops_emocion_third(self, mock_count):
        mock_count.side_effect = _over_budget_while(
            "in a simple garden", "holding/with a simple flower", "looking happy"
        )
        positive, _ = build(_params(*self._ALL), rng=Random(0))
        assert "in a simple garden" not in positive
        assert "holding/with a simple flower" not in positive
        assert "looking happy" not in positive
        assert "cute cartoon robot" in positive

    @patch("app.services.cover_prompt_builder._count_tokens")
    def test_drops_pose_fourth(self, mock_count):
        mock_count.side_effect = _over_budget_while(
            "in a simple garden",
            "holding/with a simple flower",
            "looking happy",
            *POSE_VARIANTS,
        )
        positive, _ = build(_params(*self._ALL, ("personaje", "cat")), rng=Random(0))
        assert not any(pose in positive for pose in POSE_VARIANTS)
        assert "cute cartoon robot and cat" in positive

    @patch("app.services.cover_prompt_builder._count_tokens")
    def test_trims_extra_characters_last(self, mock_count):
        mock_count.side_effect = _over_budget_while(
            "in a simple garden",
            "holding/with a simple flower",
            "looking happy",
            *POSE_VARIANTS,
            "and cat",
        )
        positive, _ = build(_params(*self._ALL, ("personaje", "cat")), rng=Random(0))
        assert "cat" not in positive
        assert "cute cartoon robot" in positive

    @patch("app.services.cover_prompt_builder._count_tokens")
    def test_personaje_never_dropped(self, mock_count):
        # Even when personaje alone is over budget, preamble stays
        mock_count.return_value = MAX_CLIP_TOKENS + 1
        positive, _ = build(_params(("personaje", "robot")))
        assert positive.startswith(STYLE_PREAMBLE)


class TestEdgeCases:
    def test_unknown_category_ignored(self):
        positive, _ = build(_params(("personaje", "robot"), ("unknown", "ignored")))
        assert "ignored" not in positive
        assert "cute cartoon robot" in positive

    def test_missing_category_key(self):
        positive, _ = build([{"value": "robot"}])
        assert positive == STYLE_PREAMBLE

    def test_missing_value_key(self):
        positive, _ = build([{"category": "personaje"}])
        assert positive == STYLE_PREAMBLE

    def test_multiple_same_category_keeps_every_character(self):
        positive, _ = build(
            [
                {"category": "personaje", "value": "robot"},
                {"category": "personaje", "value": "cat"},
            ],
            rng=Random(0),
        )
        assert "cute cartoon robot and cat" in positive

    def test_multiple_lugares_use_the_first(self):
        positive, _ = build(
            _params(("personaje", "robot"), ("lugar", "garden"), ("lugar", "castle")),
            rng=Random(0),
        )
        assert "in a simple garden" in positive
        assert "castle" not in positive


class TestCategoryNormalization:
    """Real cards carry both 'Personaje' and 'personaje' (stories.json), and a
    case-sensitive lookup silently dropped every capitalised one."""

    def test_capitalised_category_is_recognised(self):
        positive, _ = build(_params(("Personaje", "canguro")), rng=Random(0))
        assert "cute cartoon canguro" in positive

    def test_accentless_emocion_is_recognised(self):
        positive, _ = build(
            _params(("personaje", "robot"), ("Emocion", "happy")), rng=Random(0)
        )
        assert "looking happy" in positive

    def test_surrounding_whitespace_is_folded(self):
        positive, _ = build(_params(("  LUGAR  ", "castillo")), rng=Random(0))
        assert "in a simple castillo" in positive

    def test_value_whitespace_is_stripped(self):
        positive, _ = build(_params(("personaje", "  buho  ")), rng=Random(0))
        assert "cute cartoon buho" in positive


class TestMultipleCharacters:
    def test_two_personajes_both_reach_the_prompt(self):
        positive, _ = build(
            _params(("personaje", "buho"), ("Personaje", "canguro")), rng=Random(0)
        )
        assert "buho and canguro" in positive

    def test_three_personajes_are_comma_joined(self):
        positive, _ = build(
            _params(
                ("personaje", "buho"),
                ("personaje", "canguro"),
                ("personaje", "robot"),
            ),
            rng=Random(0),
        )
        assert "buho, canguro and robot" in positive

    def test_characters_are_capped(self):
        positive, _ = build(
            _params(*[("personaje", f"c{i}") for i in range(MAX_CHARACTERS + 2)]),
            rng=Random(0),
        )
        assert f"c{MAX_CHARACTERS}" not in positive


class TestVariability:
    """The kiosk complaint: identical parameters produced the same owl every
    time because the prompt was a pure function of the parameters."""

    def test_same_params_produce_different_prompts(self):
        prompts = {
            build(_params(("personaje", "buho")), rng=Random(i))[0] for i in range(30)
        }
        assert len(prompts) > 1

    def test_pose_is_drawn_from_the_pool(self):
        positive, _ = build(_params(("personaje", "buho")), rng=Random(0))
        assert any(pose in positive for pose in POSE_VARIANTS)

    def test_composition_is_drawn_from_the_pool(self):
        positive, _ = build(_params(("personaje", "buho")), rng=Random(0))
        assert any(comp in positive for comp in COMPOSITION_VARIANTS)

    def test_composition_is_not_always_the_default(self):
        comps = {
            _composition_of(build(_params(("personaje", "buho")), rng=Random(i))[0])
            for i in range(30)
        }
        assert len(comps) > 1
        assert comps <= set(COMPOSITION_VARIANTS)

    def test_explicit_rng_is_reproducible(self):
        params = _params(("personaje", "buho"), ("lugar", "castillo"))
        assert build(params, rng=Random(7))[0] == build(params, rng=Random(7))[0]

    def test_style_and_negative_survive_variation(self):
        positive, negative = build(_params(("personaje", "buho")), rng=Random(3))
        assert STYLE_HEAD in positive
        assert STYLE_TAIL in positive
        assert negative == NEGATIVE_PROMPT
