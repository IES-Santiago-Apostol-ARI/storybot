"""Tests for cover_prompt_builder — AC-1."""

from unittest.mock import patch

from app.services.cover_prompt_builder import (
    MAX_CLIP_TOKENS,
    NEGATIVE_PROMPT,
    STYLE_PREAMBLE,
    build,
)


def _params(*specs: tuple[str, str]) -> list[dict]:
    return [{"category": cat, "value": val} for cat, val in specs]


class TestStylePreamble:
    def test_positive_always_starts_with_preamble(self):
        positive, _ = build(_params(("personaje", "robot")))
        assert positive.startswith(STYLE_PREAMBLE)

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
        positive, _ = build(
            _params(("personaje", "robot"), ("objeto", "flower"))
        )
        assert "holding/with a simple flower" in positive

    def test_emocion_gets_looking_prefix(self):
        positive, _ = build(
            _params(("personaje", "robot"), ("emoción", "happy"))
        )
        assert "looking happy" in positive

    def test_problema_is_skipped(self):
        positive, _ = build(_params(("personaje", "robot"), ("problema", "fear")))
        assert "fear" not in positive
        # Only personaje phrase should be present
        assert "cute cartoon robot" in positive


class TestTokenBudgetEnforcement:
    """Drop order: lugar → objeto → emoción. personaje is never dropped."""

    @patch("app.services.cover_prompt_builder._count_tokens")
    def test_drops_lugar_first(self, mock_count):
        # call 1: over budget → drop lugar; call 2: under → stop; call 3: final OK
        mock_count.side_effect = [80, 74, 74]
        positive, _ = build(
            _params(
                ("personaje", "robot"),
                ("lugar", "garden"),
                ("objeto", "flower"),
                ("emoción", "happy"),
            )
        )
        assert "in a simple garden" not in positive
        assert "cute cartoon robot" in positive
        assert "holding/with a simple flower" in positive
        assert "looking happy" in positive

    @patch("app.services.cover_prompt_builder._count_tokens")
    def test_drops_objeto_second(self, mock_count):
        # call 1: over → drop lugar; call 2: over → drop objeto
        # call 3: under → stop; call 4: final OK
        mock_count.side_effect = [80, 78, 74, 74]
        positive, _ = build(
            _params(
                ("personaje", "robot"),
                ("lugar", "garden"),
                ("objeto", "flower"),
                ("emoción", "happy"),
            )
        )
        assert "in a simple garden" not in positive
        assert "holding/with a simple flower" not in positive
        assert "cute cartoon robot" in positive
        assert "looking happy" in positive

    @patch("app.services.cover_prompt_builder._count_tokens")
    def test_drops_emocion_third(self, mock_count):
        mock_count.side_effect = [80, 78, 76, 74]
        positive, _ = build(
            _params(
                ("personaje", "robot"),
                ("lugar", "garden"),
                ("objeto", "flower"),
                ("emoción", "happy"),
            )
        )
        assert "in a simple garden" not in positive
        assert "holding/with a simple flower" not in positive
        assert "looking happy" not in positive
        assert "cute cartoon robot" in positive

    @patch("app.services.cover_prompt_builder._count_tokens")
    def test_personaje_never_dropped(self, mock_count):
        # Even when personaje alone is over budget, preamble stays
        mock_count.return_value = MAX_CLIP_TOKENS + 1
        positive, _ = build(_params(("personaje", "robot")))
        assert positive.startswith(STYLE_PREAMBLE)


class TestEdgeCases:
    def test_unknown_category_ignored(self):
        positive, _ = build(
            _params(("personaje", "robot"), ("unknown", "ignored"))
        )
        assert "ignored" not in positive
        assert "cute cartoon robot" in positive

    def test_missing_category_key(self):
        positive, _ = build([{"value": "robot"}])
        assert positive == STYLE_PREAMBLE

    def test_missing_value_key(self):
        positive, _ = build([{"category": "personaje"}])
        assert positive == STYLE_PREAMBLE

    def test_multiple_same_category_uses_first(self):
        positive, _ = build(
            [
                {"category": "personaje", "value": "robot"},
                {"category": "personaje", "value": "cat"},
            ]
        )
        assert "cute cartoon robot" in positive
        assert "cat" not in positive
