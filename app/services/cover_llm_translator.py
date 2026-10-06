"""Spanish -> English translation of cover subjects through llama-server.

Stories are told in Spanish, but SD 1.5's CLIP text encoder only understands
English. llama-server is still up when a cover is requested (it is stopped
only when Stable Diffusion starts), so it translates the few words that go
into the prompt: card values, a story title or an admin hint.

Everything degrades to ``None``: with llama-server down, busy, slow or
answering nonsense the caller falls back to the offline rule-based
``cover_translator``. A cover must never fail because of the translation.
"""

import os
import re

import httpx

LLAMA_BASE_URL = "http://127.0.0.1:8080"
LLAMA_MODEL = "qwen35-4b-local"
# One short request; llama-server has a single slot, so a story generation in
# flight would make this queue — give up quickly and use the rules instead.
TIMEOUT_S = 8.0
# The CLIP budget is 75 tokens for the whole prompt: keep each subject short.
MAX_WORDS = 8

SYSTEM_PROMPT = (
    "You translate Spanish into English for an image generator that draws "
    "children's coloring pages. For each numbered Spanish phrase, answer with "
    "a short English noun phrase (at most 6 words) naming what to draw. "
    "Translate literally, do not add details, drop articles. For a feeling, "
    "answer with one English adjective. Keep the same numbering, one phrase "
    "per line, and write nothing else."
)

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
_NUMBERED_LINE = re.compile(r"^\s*(\d+)\s*[.):-]\s*(.+?)\s*$")
_NOT_ALLOWED = re.compile(r"[^a-z0-9 '-]+")


def _clean(text: str) -> str | None:
    """Reduce a model answer to a plain lowercase English phrase, or None."""
    phrase = _NOT_ALLOWED.sub(" ", text.lower().replace("’", "'"))
    words = phrase.split()
    if not words or not any(c.isalpha() for c in phrase):
        return None
    return " ".join(words[:MAX_WORDS])


def _parse(content: str, count: int) -> list[str | None]:
    """Map the numbered lines of the answer back onto the request order."""
    result: list[str | None] = [None] * count
    for line in _THINK_BLOCK.sub("", content).splitlines():
        match = _NUMBERED_LINE.match(line)
        if not match:
            continue
        index = int(match.group(1)) - 1
        if 0 <= index < count and result[index] is None:
            result[index] = _clean(match.group(2))
    return result


async def translate_values(
    values: list[str],
    *,
    base_url: str = LLAMA_BASE_URL,
    model: str = LLAMA_MODEL,
    timeout_s: float = TIMEOUT_S,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[str | None]:
    """Translate each Spanish value to a short English phrase.

    Returns one entry per input, in order; an entry is ``None`` when no usable
    translation came back for it (the caller then uses the rule-based one).

    ``transport`` is the test seam (``httpx.MockTransport``). Under ``TESTING``
    without a transport nothing is sent, so the suite never talks to a real
    llama-server that happens to be running on the machine.
    """
    blank: list[str | None] = [None] * len(values)
    wanted = [(i, v.strip()) for i, v in enumerate(values) if v and v.strip()]
    if not wanted or (transport is None and os.environ.get("TESTING")):
        return blank

    numbered = "\n".join(f"{n}. {v}" for n, (_, v) in enumerate(wanted, start=1))
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 24 * len(wanted),
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": numbered},
        ],
    }
    try:
        async with httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_s, connect=2.0),
            transport=transport,
        ) as client:
            response = await client.post("/v1/chat/completions", json=payload)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        return blank

    for (index, _), phrase in zip(wanted, _parse(content or "", len(wanted))):
        blank[index] = phrase
    return blank
