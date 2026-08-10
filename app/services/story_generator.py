"""StoryGenerator — streaming LLM client for llama-server OpenAI-compat endpoint."""

import json
from collections.abc import AsyncGenerator

import httpx

SYSTEM_PREAMBLE = (
    "Eres un narrador de cuentos infantiles en español para niños de 3 a 6 años.\n"
    "Cada historia debe:\n"
    "- Usar un vocabulario sencillo y cotidiano en español, sin extranjerismos "
    "salvo palabras muy comunes.\n"
    "- Tener un arco narrativo claro: presentación del personaje y el entorno, "
    "un pequeño conflicto o problema, y una resolución tranquila y positiva.\n"
    "- Desarrollarse en 3 a 5 párrafos cortos, cada uno de 2 a 4 frases.\n"
    "- Terminar la historia en este turno — no preguntes nada al final ni dejes "
    "la historia abierta.\n"
    "- Incluir por nombre a todos los personajes, lugares, objetos y emociones "
    "que se mencionen en la consigna del usuario. Todos deben aparecer y ser "
    "relevantes en la historia.\n"
    "- Escribir solo prosa narrativa. Sin títulos, sin encabezados, sin listas, "
    "sin metadatos. Solo el texto del cuento."
)


def _partial_tag_len(text: str, tag: str) -> int:
    """Length of the longest proper prefix of ``tag`` that ``text`` ends with.

    Lets the filter hold back a trailing ``"<th"`` until the next delta
    resolves it into either ``<think>`` or ordinary text.
    """
    for size in range(min(len(tag) - 1, len(text)), 0, -1):
        if text.endswith(tag[:size]):
            return size
    return 0


class _ThinkFilter:
    """Strips ``<think>…</think>`` spans from a token stream.

    Qwen3.5 emits an (often empty) think block in ``content`` even with
    ``--reasoning off --reasoning-format none``, so the tags reach the story
    text and get narrated by Piper. Tags arrive split across deltas, so this
    keeps a small buffer instead of filtering each delta in isolation.

    One instance per generation — never shared between concurrent streams.
    """

    _OPEN = "<think>"
    _CLOSE = "</think>"

    def __init__(self) -> None:
        self._buf = ""
        self._in_think = False
        self._emitted = False

    def feed(self, chunk: str) -> str:
        self._buf += chunk
        out: list[str] = []
        while self._buf:
            if self._in_think:
                idx = self._buf.find(self._CLOSE)
                if idx == -1:
                    keep = _partial_tag_len(self._buf, self._CLOSE)
                    self._buf = self._buf[len(self._buf) - keep :] if keep else ""
                    break
                self._buf = self._buf[idx + len(self._CLOSE) :]
                self._in_think = False
                continue

            idx = self._buf.find(self._OPEN)
            if idx == -1:
                keep = _partial_tag_len(self._buf, self._OPEN)
                emit = self._buf[: len(self._buf) - keep] if keep else self._buf
                self._buf = self._buf[len(emit) :]
                out.append(emit)
                break

            out.append(self._buf[:idx])
            self._buf = self._buf[idx + len(self._OPEN) :]
            self._in_think = True

        return self._clean("".join(out))

    def flush(self) -> str:
        """Emit any held-back partial tag that never completed."""
        if self._in_think:
            return ""
        rest, self._buf = self._buf, ""
        return self._clean(rest)

    def _clean(self, text: str) -> str:
        if not self._emitted:
            # Drop the blank lines the closing tag leaves before the story.
            text = text.lstrip()
        if text:
            self._emitted = True
        return text


class StoryGenerator:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        model: str = "qwen35-4b-local",
        temperature: float = 0.8,
        top_p: float = 0.95,
        max_tokens: int = 600,
        timeout: int = 600,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens
        self.timeout = timeout
        # Test seam: an httpx.MockTransport here keeps tests off the network.
        self._transport = transport

    def _build_user_message(self, parameters: list[dict]) -> str:
        parts = [f"{p['category']}={p['value']}" for p in parameters]
        return f"Cuenta una historia con estos elementos: {', '.join(parts)}."

    def _build_payload(self, parameters: list[dict]) -> dict:
        return {
            "model": self.model,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "stream": True,
            "messages": [
                {"role": "system", "content": SYSTEM_PREAMBLE},
                {"role": "user", "content": self._build_user_message(parameters)},
            ],
        }

    async def generate_story(
        self, parameters: list[dict]
    ) -> AsyncGenerator[dict, None]:
        """Stream story tokens from llama-server as {"text", "done"} events.

        Runs natively on httpx.AsyncClient — no thread/queue bridge, and
        parameters flow as arguments (no shared instance state between
        concurrent generations). Any transport or HTTP-status failure
        (llama-server down, still warming up after a cover swap, 5xx) is
        reported as a terminal {"error": ..., "done": True} event instead of
        raising, so the SSE route never dies mid-stream.
        """
        url = f"{self.base_url}/v1/chat/completions"
        # Fail fast when the server is unreachable; stay patient once the
        # stream is open (token gaps on the Jetson can be long).
        timeout = httpx.Timeout(self.timeout, connect=5.0)
        finish_reason: str | None = None
        think = _ThinkFilter()
        try:
            async with httpx.AsyncClient(
                timeout=timeout, transport=self._transport
            ) as client:
                async with client.stream(
                    "POST", url, json=self._build_payload(parameters)
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data.strip() == "[DONE]":
                            break

                        try:
                            obj = json.loads(data)
                        except json.JSONDecodeError:
                            continue

                        choices = obj.get("choices", [])
                        if not choices:
                            continue

                        if choices[0].get("finish_reason") is not None:
                            finish_reason = choices[0]["finish_reason"]

                        content = choices[0].get("delta", {}).get("content")
                        if content is None:
                            continue

                        # --reasoning off is not honoured by Qwen3.5, which
                        # still emits <think></think> inside `content`; strip
                        # it here so the tags never reach the story or Piper.
                        visible = think.feed(content)
                        if visible:
                            yield {"text": visible, "done": False}

                    tail = think.flush()
                    if tail:
                        yield {"text": tail, "done": False}
        except httpx.HTTPError:
            yield {"error": "Failed to connect to llama-server", "done": True}
            return

        # IMPROVEMENTS.md 3.2: max_tokens cut the story short — mark the
        # sentinel so the route can drop the mid-word tail instead of
        # narrating it. Normal completions keep the exact legacy shape.
        if finish_reason == "length":
            yield {"text": None, "done": True, "truncated": True}
        else:
            yield {"text": None, "done": True}
