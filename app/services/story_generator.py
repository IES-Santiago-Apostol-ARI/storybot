"""StoryGenerator — streaming LLM client for llama-server OpenAI-compat endpoint."""

import asyncio
import json
import re
import threading
from collections.abc import AsyncGenerator

import requests

SYSTEM_PREAMBLE = (
    "Eres un narrador de cuentos infantiles en español para niños de 3 a 6 años.\n"
    "Cada historia debe:\n"
    "- Usar un vocabulario sencillo y cotidiano en español, sin extranjerismos salvo palabras muy comunes.\n"
    "- Tener un arco narrativo claro: presentación del personaje y el entorno, un pequeño conflicto o problema, y una resolución tranquila y positiva.\n"
    "- Desarrollarse en 3 a 5 párrafos cortos, cada uno de 2 a 4 frases.\n"
    "- Terminar la historia en este turno — no preguntes nada al final ni dejes la historia abierta.\n"
    "- Incluir por nombre a todos los personajes, lugares, objetos y emociones que se mencionen en la consigna del usuario. Todos deben aparecer y ser relevantes en la historia.\n"
    "- Escribir solo prosa narrativa. Sin títulos, sin encabezados, sin listas, sin metadatos. Solo el texto del cuento."
)


class StoryGenerator:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        model: str = "qwen35-4b-local",
        temperature: float = 0.8,
        top_p: float = 0.95,
        max_tokens: int = 600,
        timeout: int = 600,
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens
        self.timeout = timeout

    def _build_user_message(self, parameters: list[dict]) -> str:
        parts = [f"{p['category']}={p['value']}" for p in parameters]
        return f"Cuenta una historia con estos elementos: {', '.join(parts)}."

    def _strip_think_tags(self, text: str) -> str:
        if not text:
            return ""
        stripped = re.sub(r"<think\s*/>?", "", text, flags=re.DOTALL)
        stripped = re.sub(r"<think\b.*?</think\b", "", stripped, flags=re.DOTALL)
        stripped = stripped.lstrip("\n\r")
        return stripped

    def _fetch_stream(self) -> requests.Response | None:
        """Run the blocking requests.post in a thread and return the response."""
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "stream": True,
            "messages": [
                {"role": "system", "content": SYSTEM_PREAMBLE},
                {"role": "user", "content": self._build_user_message(self._params)},
            ],
        }
        try:
            resp = requests.post(
                url, json=payload, stream=True, timeout=self.timeout
            )
            resp.raise_for_status()
            return resp
        except (requests.ConnectionError, requests.Timeout) as e:
            return None

    async def generate_story(self, parameters: list[dict]) -> AsyncGenerator[dict, None]:
        """Async generator that streams tokens from llama-server.

        The blocking requests.post call is run in a background thread. SSE lines
        are collected in a queue and yielded from the async side to avoid blocking
        the FastAPI event loop.
        """
        self._params = parameters
        resp = await asyncio.to_thread(self._fetch_stream)

        if resp is None:
            yield {"error": "Failed to connect to llama-server", "done": True}
            return

        # Queue to bridge blocking reader → async consumer
        queue: asyncio.Queue = asyncio.Queue()

        def read_stream():
            """Background thread: reads SSE lines and pushes to queue."""
            try:
                for line in resp.iter_lines():
                    queue.put_nowait(line)
            except Exception:
                pass
            finally:
                queue.put_nowait(None)  # Sentinel

        threading.Thread(target=read_stream, daemon=True).start()

        while True:
            line = await queue.get()
            if line is None:
                break
            if not line:
                continue
            line = line.decode("utf-8", errors="replace")
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

            delta = choices[0].get("delta", {})
            content = delta.get("content")

            if content is None:
                continue

            cleaned = self._strip_think_tags(content)
            if cleaned:
                yield {"text": cleaned, "done": False}

        yield {"text": None, "done": True}
