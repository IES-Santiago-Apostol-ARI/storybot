"""SentenceBuffer — incremental Spanish sentence detector."""

ABBREVIATIONS = frozenset(
    {"Sr", "Sra", "Sres", "Dr", "Dra", "Srta", "etc", "p.ej", "vs"}
)

TERMINATORS = frozenset(".!?…")


class SentenceBuffer:
    """Accumulates text chunks and returns complete sentences.

    Detects sentence boundaries at terminators (. ! ? …) followed by
    whitespace or end-of-input, while guarding against Spanish abbreviations.
    """

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, chunk: str) -> list[str]:
        self._buf += chunk
        return self._extract()

    def flush(self) -> list[str]:
        if not self._buf.strip():
            self._buf = ""
            return []
        sentence = self._buf.strip()
        self._buf = ""
        return [sentence]

    def _extract(self) -> list[str]:
        sentences = []
        i = 0
        while i < len(self._buf):
            if self._buf[i] in TERMINATORS:
                end = i + 1
                # Check if this period belongs to an abbreviation
                if self._buf[i] == "." and self._is_abbreviation(i):
                    i = end
                    continue
                # Consume whitespace after terminator
                while end < len(self._buf) and self._buf[end] == " ":
                    end += 1
                # Sentence is complete if there's whitespace or end-of-buffer
                if end > i + 1 or i + 1 == len(self._buf):
                    raw = self._buf[:end].strip()
                    if raw:
                        sentences.append(raw)
                    self._buf = self._buf[end:]
                    i = 0
                    continue
            i += 1
        return sentences

    def _is_abbreviation(self, period_pos: int) -> bool:
        start = period_pos - 1
        while start >= 0 and self._buf[start].isalpha():
            start -= 1
        word = self._buf[start + 1 : period_pos]
        return word in ABBREVIATIONS
