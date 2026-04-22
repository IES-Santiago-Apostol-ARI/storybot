"""Tests for SentenceBuffer — incremental Spanish sentence detector."""

from app.services.sentence_buffer import SentenceBuffer


class TestSentenceBufferEmpty:
    def test_feed_empty_returns_empty(self):
        buf = SentenceBuffer()
        assert buf.feed("") == []

    def test_flush_empty_returns_empty(self):
        buf = SentenceBuffer()
        assert buf.flush() == []


class TestSentenceBufferSingleSentence:
    def test_incremental_chars(self):
        buf = SentenceBuffer()
        results = []
        for ch in "Hola.":
            results.extend(buf.feed(ch))
        # Period alone doesn't complete — need whitespace or flush
        results.extend(buf.flush())
        assert results == ["Hola."]

    def test_incremental_chars_with_trailing_space(self):
        buf = SentenceBuffer()
        results = []
        for ch in "Hola. ":
            results.extend(buf.feed(ch))
        assert results == ["Hola."]

    def test_exclamation_mark(self):
        buf = SentenceBuffer()
        results = buf.feed("¡Hola! ")
        assert results == ["¡Hola!"]

    def test_question_mark(self):
        buf = SentenceBuffer()
        results = buf.feed("¿Qué tal? ")
        assert results == ["¿Qué tal?"]


class TestSentenceBufferMultiSentence:
    def test_multi_sentence_single_chunk(self):
        buf = SentenceBuffer()
        results = buf.feed("Hola. Adiós!")
        assert results == ["Hola.", "Adiós!"]

    def test_multi_sentence_across_chunks(self):
        buf = SentenceBuffer()
        results = []
        results.extend(buf.feed("Había una vez un dragón. "))
        results.extend(buf.feed("Vivía en una montaña."))
        results.extend(buf.flush())
        assert results == [
            "Había una vez un dragón.",
            "Vivía en una montaña.",
        ]

    def test_spanish_punctuation_terminators(self):
        buf = SentenceBuffer()
        results = buf.feed("Primero. Segundo! Tercero? ")
        assert results == ["Primero.", "Segundo!", "Tercero?"]


class TestSentenceBufferEllipsis:
    def test_ellipsis_splits(self):
        buf = SentenceBuffer()
        results = buf.feed("Esperó… y nada.")
        results.extend(buf.flush())
        assert results == ["Esperó…", "y nada."]


class TestSentenceBufferAbbreviations:
    def test_sr_no_split(self):
        buf = SentenceBuffer()
        results = buf.feed("El Sr. García saludó. Luego se fue.")
        results.extend(buf.flush())
        assert results == ["El Sr. García saludó.", "Luego se fue."]

    def test_sra_no_split(self):
        buf = SentenceBuffer()
        results = buf.feed("La Sra. López llegó. Se sentó.")
        results.extend(buf.flush())
        assert results == ["La Sra. López llegó.", "Se sentó."]

    def test_dr_no_split(self):
        buf = SentenceBuffer()
        results = buf.feed("El Dr. Pérez habló. Todos escucharon.")
        results.extend(buf.flush())
        assert results == ["El Dr. Pérez habló.", "Todos escucharon."]

    def test_etc_no_split(self):
        buf = SentenceBuffer()
        results = buf.feed("Compró frutas, verduras, etc. y volvió.")
        results.extend(buf.flush())
        # "etc." followed by space should NOT split (abbreviation guard)
        assert len(results) == 1

    def test_vs_no_split(self):
        buf = SentenceBuffer()
        results = buf.feed("Era perros vs. gatos. Ganaron los gatos.")
        results.extend(buf.flush())
        assert results == ["Era perros vs. gatos.", "Ganaron los gatos."]


class TestSentenceBufferWhitespace:
    def test_leading_whitespace_trimmed(self):
        buf = SentenceBuffer()
        results = buf.feed("  Hola.  Adiós.")
        results.extend(buf.flush())
        assert results[0] == "Hola."
        assert results[1] == "Adiós."

    def test_internal_spacing_preserved(self):
        buf = SentenceBuffer()
        results = buf.feed("Hola  mundo. ")
        assert results == ["Hola  mundo."]

    def test_flush_returns_remaining(self):
        buf = SentenceBuffer()
        buf.feed("Sin punto final")
        assert buf.flush() == ["Sin punto final"]

    def test_flush_after_complete_returns_empty(self):
        buf = SentenceBuffer()
        buf.feed("Completo. ")
        assert buf.flush() == []
