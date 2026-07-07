"""Tests for StoryGenerator service."""

import json

import httpx
import pytest

from app.services.story_generator import SYSTEM_PREAMBLE, StoryGenerator


class TestBuildUserMessage:
    def test_two_params(self):
        sg = StoryGenerator()
        params = [
            {"category": "personaje", "value": "dragón amable"},
            {"category": "objeto", "value": "llave mágica"},
        ]
        msg = sg._build_user_message(params)
        assert msg == "Cuenta una historia con estos elementos: personaje=dragón amable, objeto=llave mágica."

    def test_single_param(self):
        sg = StoryGenerator()
        params = [{"category": "emoción", "value": "alegría"}]
        msg = sg._build_user_message(params)
        assert msg == "Cuenta una historia con estos elementos: emoción=alegría."

    def test_four_params(self):
        sg = StoryGenerator()
        params = [
            {"category": "personaje", "value": "gato astronauta"},
            {"category": "lugar", "value": "luna"},
            {"category": "objeto", "value": "pelota"},
            {"category": "problema", "value": "extrañar su casa"},
        ]
        msg = sg._build_user_message(params)
        assert "personaje=gato astronauta" in msg
        assert "lugar=luna" in msg
        assert "objeto=pelota" in msg
        assert "problema=extrañar su casa" in msg


class TestSystemPreamble:
    def test_contains_spanish_narrator(self):
        assert "narrador de cuentos infantiles" in SYSTEM_PREAMBLE

    def test_contains_age_range(self):
        assert "3 a 6 años" in SYSTEM_PREAMBLE

    def test_contains_end_instruction(self):
        assert "Terminar la historia en este turno" in SYSTEM_PREAMBLE

    def test_contains_prose_only(self):
        assert "solo prosa narrativa" in SYSTEM_PREAMBLE

    def test_no_english(self):
        # All characters should be Spanish/Unicode, no English sentences
        assert "the " not in SYSTEM_PREAMBLE.lower()
        assert "and " not in SYSTEM_PREAMBLE.lower()


class TestStripThinkTags:
    def test_strips_think_block(self):
        sg = StoryGenerator()
        text = "<think\nSome reasoning here\n</think\n\nThe story text"
        assert sg._strip_think_tags(text) == "The story text"

    def test_no_tags_returns_original(self):
        sg = StoryGenerator()
        text = "Una historia simple."
        assert sg._strip_think_tags(text) == "Una historia simple."

    def test_empty_string(self):
        sg = StoryGenerator()
        assert sg._strip_think_tags("") == ""

    def test_think_with_attributes(self):
        sg = StoryGenerator()
        text = '<think type="reasoning"\nreasoning\n</think\n\nHello'
        assert sg._strip_think_tags(text) == "Hello"

    def test_self_closing_think(self):
        sg = StoryGenerator()
        text = "<think/\n\nWorld"
        assert sg._strip_think_tags(text) == "World"


class TestGenerateStory:
    """Streaming behavior via an injected httpx.MockTransport (no thread,
    no requests — IMPROVEMENTS.md 1.10)."""

    def _transport(self, body: str, status_code: int = 200):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code, content=body.encode("utf-8"))

        return httpx.MockTransport(handler)

    async def _collect(self, sg, params):
        """Collect all events from the async generator."""
        return [e async for e in sg.generate_story(params)]

    @pytest.mark.asyncio
    async def test_streams_text(self):
        body = (
            'data: {"choices":[{"delta":{"content":"Hola "}}]}\n'
            'data: {"choices":[{"delta":{"content":"mundo"}}]}\n'
            "data: [DONE]\n"
        )
        sg = StoryGenerator(transport=self._transport(body))
        events = await self._collect(sg, [{"category": "personaje", "value": "dragón"}])

        assert len(events) == 3
        assert events[0] == {"text": "Hola ", "done": False}
        assert events[1] == {"text": "mundo", "done": False}
        assert events[2] == {"text": None, "done": True}

    @pytest.mark.asyncio
    async def test_skips_reasoning_content(self):
        body = (
            'data: {"choices":[{"delta":{"role":"assistant","content":null}}]}\n'
            'data: {"choices":[{"delta":{"reasoning_content":"thinking..."}}]}\n'
            'data: {"choices":[{"delta":{"content":"Story text"}}]}\n'
            "data: [DONE]\n"
        )
        sg = StoryGenerator(transport=self._transport(body))
        events = await self._collect(sg, [{"category": "lugar", "value": "jardín"}])

        text_events = [e for e in events if e.get("text")]
        assert len(text_events) == 1
        assert text_events[0]["text"] == "Story text"

    @pytest.mark.asyncio
    async def test_strips_think_tags_from_chunks(self):
        body = (
            'data: {"choices":[{"delta":{"content":'
            '"<think\\n\\n</think\\n\\nUna historia"}}]}\n'
            "data: [DONE]\n"
        )
        sg = StoryGenerator(transport=self._transport(body))
        events = await self._collect(sg, [{"category": "objeto", "value": "pelota"}])

        text_events = [e for e in events if e.get("text")]
        assert "<think" not in text_events[0]["text"]
        assert "Una historia" in text_events[0]["text"]

    @pytest.mark.asyncio
    async def test_connection_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        sg = StoryGenerator(transport=httpx.MockTransport(handler))
        events = await self._collect(sg, [{"category": "personaje", "value": "robot"}])

        assert len(events) == 1
        assert "error" in events[0]
        assert events[0]["done"] is True

    @pytest.mark.asyncio
    async def test_http_status_error_yields_error_event(self):
        """IMPROVEMENTS.md 1.4: a 5xx from llama-server (e.g. still warming
        up right after a cover swap) must yield a terminal error event —
        never raise out of the generator and kill the SSE route."""
        sg = StoryGenerator(transport=self._transport("loading", status_code=503))
        events = await self._collect(sg, [{"category": "personaje", "value": "oso"}])

        assert len(events) == 1
        assert "error" in events[0]
        assert events[0]["done"] is True

    @pytest.mark.asyncio
    async def test_sends_correct_payload(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, content=b"data: [DONE]\n")

        sg = StoryGenerator(
            temperature=0.7, top_p=0.9, max_tokens=500,
            transport=httpx.MockTransport(handler),
        )
        await self._collect(sg, [{"category": "personaje", "value": "dragón"}])

        payload = captured["payload"]
        assert payload["model"] == "qwen35-4b-local"
        assert payload["temperature"] == 0.7
        assert payload["top_p"] == 0.9
        assert payload["max_tokens"] == 500
        assert payload["stream"] is True
        assert len(payload["messages"]) == 2
        assert payload["messages"][0]["role"] == "system"
        assert payload["messages"][1]["role"] == "user"
        assert "dragón" in payload["messages"][1]["content"]

    @pytest.mark.asyncio
    async def test_concurrent_generations_do_not_share_state(self):
        """IMPROVEMENTS.md 1.10: parameters must flow as arguments, not via
        mutable instance state — two interleaved generations on the same
        StoryGenerator each get their own user message."""
        seen_messages: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            seen_messages.append(payload["messages"][1]["content"])
            return httpx.Response(200, content=b"data: [DONE]\n")

        sg = StoryGenerator(transport=httpx.MockTransport(handler))
        gen_a = sg.generate_story([{"category": "personaje", "value": "gato"}])
        gen_b = sg.generate_story([{"category": "personaje", "value": "perro"}])
        # Interleave: start both before finishing either.
        await gen_a.__anext__()
        await gen_b.__anext__()

        assert any("gato" in m for m in seen_messages)
        assert any("perro" in m for m in seen_messages)
