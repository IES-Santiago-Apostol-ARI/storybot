# StoryBot — Review Findings & Fix Plan

Source: full-code review session (2026-07-07). Targets are **exclusively**:
NVIDIA Jetson Orin Nano Super 8GB (AI mode) and Arduino UNO Q (non-AI mode).
Repo docs describing other targets are outdated.

Legend: `[ ]` pending · `[x]` fixed (with session date).

---

## 1. Bugs

### 1.1 `[x]` Kiosk abandons generation stream at story sentinel — covers never shown (2026-07-07)

- **Where:** `static/children/script.js` (read loop of the `/api/generate/story`
  fetch, ~line 1028) + `app/routers/generate.py` (event ordering).
- **Symptom:** Client `return`s when it sees the sentinel
  `{"text": null, "done": true}`. The backend emits that sentinel **before**
  (a) flushing the last unterminated sentence's `audio_ready` and (b) the
  `cover_ready`/`cover_failed` events (cover gen takes 60–120 s). So the
  THANKYOU cover swap (`bufferedCoverUrl`, applied at the THANKYOU transition)
  can never fire from this path, and a trailing sentence's audio is dropped.
  The `try { console.timeEnd('cover-roundtrip') } catch` wrapper is the tell.
- **Fix (applied):**
  1. Backend: after the TTS flush loop, emit an explicit
     `{"audio_complete": true}` SSE event before starting cover generation.
  2. Frontend: on the sentinel, do nothing (keep reading). On
     `audio_complete`, call `generationAudioQueue.markStreamComplete()` and
     keep reading until the server closes the stream (stream end also calls
     `markStreamComplete()` as a fallback for old backends / error paths).
     The queue's completion callback is now fire-once (double
     `markStreamComplete` must not fire THANKYOU twice), and a `cover_ready`
     landing during THANKYOU applies immediately instead of being dropped
     (the cover elements stay on screen ~4 s there).

### 1.2 `[x]` `/static/generated` not mounted on fresh installs (2026-07-07)

- **Where:** `app/main.py` (module-level mounts), `deploy/install.sh:323-325`.
- **Symptom:** Mounts are conditional on the directory existing **at import
  time**; install.sh creates `content/stories`, `content/interactive`,
  `content/images` but never `content/generated`. On first boot the first AI
  story's audio/cover URLs 404 until the service restarts.
- **Fix (applied):** `mkdir(parents=True, exist_ok=True)` the two content dirs
  right before mounting and mount unconditionally (kiosk/admin/shared mounts
  stay conditional — they ship with the repo).
- Also added `content/generated` to install.sh's mkdir list for symmetry.

### 1.3 `[ ]` NFC `stop_polling` signature mismatch crashes SSE cleanup on mock hardware

- **Where:** `app/routers/nfc.py:152` calls
  `await nfc_service.stop_polling(card_callback)`;
  `app/services/nfc_handler.py` — `MockNFCService.stop_polling(self)` (~line
  243) takes no argument; the base `NFCService.stop_polling(self)` protocol
  (~line 37) also declares no argument. `RealNFCService.stop_polling(self,
  callback=None)` does.
- **Symptom:** On any device where pyscard fails to import (Arduino UNO Q
  without libpcsclite/pcscd) the factory returns `MockNFCService`; every SSE
  disconnect then raises `TypeError` in the generator's `finally`.
- **Fix:**
  1. Change base protocol and `MockNFCService` to
     `async def stop_polling(self, callback: Callable[[str], None] | None = None) -> None`.
  2. Make `MockNFCService` keep a `list` of callbacks (like Real) and remove
     only the passed one; `start_polling` should append, not overwrite —
     kiosk + admin can be connected simultaneously.
  3. Test: register two callbacks on the mock, `simulate_tap`, assert both
     fire; `stop_polling(cb1)`, tap again, assert only cb2 fires.

### 1.4 `[ ]` LLM stream errors kill the SSE stream and strand the LED in THINKING

- **Where:** `app/services/story_generator.py:66-73` (`_fetch_stream` catches
  only `requests.ConnectionError`/`requests.Timeout` — `raise_for_status()`
  raises `requests.HTTPError` which escapes), and
  `app/routers/generate.py` `stream()` (no try/finally around the body).
- **Symptom:** A 4xx/5xx from llama-server (e.g. still warming up right after
  a cover swap) propagates out of `asyncio.to_thread`, aborts the
  StreamingResponse with no `{"error": ...}` event; the animator stays in
  THINKING/PROGRESS. A client disconnect mid-generation (`GeneratorExit`)
  leaves the LED stuck the same way.
- **Fix:**
  1. In `_fetch_stream`, catch `requests.RequestException` (superclass) and
     return None.
  2. In `generate.py` `stream()`, wrap the whole body in
     `try: ... except Exception: yield error event; animator ERROR`
     `finally: if animator set_mode(Mode.IDLE) unless a story finished
     normally` — at minimum guarantee the animator leaves
     THINKING/PROGRESS on GeneratorExit/exception. Careful: don't clobber the
     ERROR blink (it auto-fades, D-16) — setting IDLE only on GeneratorExit
     and unexpected exceptions is enough.
  3. Test: monkeypatch story_generator to raise mid-stream; assert the
     response terminates with an error event and animator mode was reset.

### 1.5 `[x]` Test suite: deadlocking SSE test + stale EventHub assertion (2026-07-07)

- **Where:**
  `tests/test_api/test_system.py::TestSystemEventsStream::test_events_streams_published_interrupt`
  and
  `tests/test_services/test_gpio_dispatcher.py::TestLifespan::test_lifespan_dispatcher_task_and_queues`.
- **Symptom:** (a) The first test drove an **infinite** SSE stream through
  `client.stream(...)` — starlette's TestClient transport buffers the complete
  response body before returning headers, so `__enter__` never returns and the
  whole suite hangs (exit 143 under `timeout`); its cross-thread bare
  `put_nowait` into an `asyncio.Queue` was a second latent deadlock. (b) The
  second still asserted `isinstance(app.state.kiosk_events, asyncio.Queue)` —
  stale since commit `a6082bc` replaced the bare Queue with `EventHub`.
- **Fix (applied):** (a) rewrote the test to invoke the `system_events` route
  handler directly and consume `response.body_iterator` in-loop (the
  `TestNFCEventStreamLogic` pattern), publishing on the hub between
  subscription and the first `__anext__` result; also asserts unsubscribe on
  `aclose()`. (b) assert `isinstance(app.state.kiosk_events, EventHub)`.
- **Rule of thumb:** never drive endless SSE endpoints through TestClient;
  test the generator, and use TestClient only for streams that terminate.
- **Note:** production is NOT affected — GpioDispatcher publishes from inside
  the loop, and GPIO edge callbacks use `loop.call_soon_threadsafe`.

### 1.6 `[ ]` `hardware.rescan()` leaks live services (duplicate NFC events, double Piper RAM)

- **Where:** `app/services/hardware_manager.py:90-97` (`rescan` →
  `detect_hardware` re-registers without shutting down).
- **Symptom:** The old NFC `CardMonitor` observer keeps firing (each tap can
  invoke callbacks registered on the *old* service), and Piper (~400 MB) is
  loaded a second time while the old engine is still referenced — a real
  spike on 8 GB.
- **Fix:** at the top of `detect_hardware` (or in `rescan` before calling
  it), iterate the services about to be replaced (`tts`, `nfc`, `led`,
  `audio`) and `await service.shutdown()` on each; only then create new
  instances. Do NOT shut down `gpio` (registered separately by the lifespan).
  Test: register a fake nfc service with a spy `shutdown()`, call `rescan`,
  assert it was awaited.

### 1.7 `[ ]` `tts_voice` config is dead

- **Where:** `app/config.py:42` (`tts_voice: "es_ES-glow_tenor"` — a voice
  that doesn't even exist in the download script) vs
  `app/services/tts_engine.py:37` (hardcoded `es_ES-sharvard-medium`),
  `deploy/download-models.sh` (downloads sharvard).
- **Fix:** pass `ConfigManager().load().tts_voice` into
  `TTSEngine.initialize()` → `load_model(model_name=settings.tts_voice)`, and
  change the config default to `es_ES-sharvard-medium` so config matches
  reality. Keep this field — it becomes the engine/voice selector when the
  pocket-tts engine lands (§4).

### 1.8 `[ ]` GPIO docstring contradicts code; Jetson.GPIO ignores pull configuration

- **Where:** `app/services/gpio_handler.py` class docstring ("internal
  pull-up and falling-edge") vs code `PUD_DOWN` + `GPIO.RISING` (~lines
  105-113).
- **Fix:** fix the docstring to "pull-down + rising edge (button ties pin to
  3.3 V)". Add a comment that Jetson.GPIO **ignores** `pull_up_down` (pulls
  come from pinmux/jetson-io), so external pull-downs are required or
  floating inputs will produce phantom presses. Cross-check `gpio_usage.md`.

### 1.9 `[ ]` Hardcoded `/home/ari` in swap orchestrator

- **Where:** `app/services/swap_orchestrator.py:12`
  (`SD_VENV_PYTHON = Path("/home/ari/sd-cover/.venv/bin/python")`) —
  inconsistent with `Path.home() / "sd-cover/..."` used in
  `cover_prompt_builder.py:22` and `scripts/sd_cover_worker.py:23-25`.
- **Symptom:** any Jetson whose user isn't `ari` fails every cover *after*
  paying the llama stop/start cycle.
- **Fix:** `SD_VENV_PYTHON = Path.home() / "sd-cover/.venv/bin/python"`.
  Optionally make it a `Settings` field.

### 1.10 `[ ]` `requests` is a runtime import but only a dev dependency

- **Where:** `app/services/story_generator.py:9`; `pyproject.toml`
  `[dependency-groups].dev` contains `requests`.
- **Symptom:** `uv sync --no-dev` (natural prod invocation) removes requests →
  story generation import error.
- **Fix (preferred):** rewrite `StoryGenerator.generate_story` on
  `httpx.AsyncClient` (already a core dep):
  `async with client.stream("POST", url, json=payload, timeout=...)` +
  `async for line in resp.aiter_lines()`. This also removes the thread+queue
  bridge, the `read_stream` machinery, and the hidden `self._params` shared
  state (a race if two generations ever overlap — pass `parameters` as an
  argument to `_build_user_message` at call time instead of stashing on
  `self`). Use `httpx.Timeout(connect=5, read=self.timeout, ...)` so a hung
  server fails fast on connect. Alternative quick fix: move `requests` to
  core deps (worse).

### 1.11 `[ ]` `_strip_think_tags` is ineffective for streamed tags

- **Where:** `app/services/story_generator.py:44-50`.
- **Detail:** tags split across deltas never match (each delta is processed
  independently), and the `r"<think\b.*?</think\b"` regex leaves a stray `>`
  even on a whole-tag match. Moot in production because
  `deploy/llama-server.service` runs `--reasoning off --reasoning-format
  none`, but as written it's dead-ish, misleading code.
- **Fix:** either delete it (rely on the server flags) or implement a small
  stateful filter (track "inside think block" across chunks, buffer partial
  `<`-prefixes). Deleting + a comment pointing at the service flags is the
  surgical option.

## 2. Duplicated / unneeded code

### 2.1 `[ ]` `audio_ready` synthesis block duplicated verbatim in generate.py

- **Where:** `app/routers/generate.py` — main loop (~127-171) and flush
  (~184-220) are the same ~35 lines.
- **Fix:** extract
  `async def _synth_and_events(sentence, story_id, seg_index, tts_pipeline, animator, segments) -> AsyncIterator[str]`
  (or a small local closure) that synthesizes one sentence, appends to
  `segments`, and yields the SSE strings + drives the LED progress/error
  modes. Call it from both places. Behavior must stay byte-identical
  (existing tests in `tests/test_api/test_generate.py` pin the event shapes).

### 2.2 `[ ]` `_hex_to_rgb` implemented three times

- **Where:** `app/routers/generate.py:31`, `app/routers/system.py:95`,
  `app/services/led_animator.py:62`.
- **Fix:** single `hex_to_rgb` in `app/services/led_effects.py` (neutral,
  imported by all three without router-into-router imports). Re-export or
  alias where tests reference the old names.

### 2.3 `[ ]` Five module-level `ConfigManager().load()` singletons

- **Where:** `generate.py:28`, `gpio_handler.py:14`, `gpio_dispatcher.py:31`,
  `system_control.py:15`, `led_animator.py:54`.
- **Problem:** each keeps a private `Settings` copy read at import; admin
  `reload()` on `app.state.config` never reaches them.
- **Fix:** add a module-level accessor in `app/config.py`
  (`get_settings()` returning a process-wide cached instance with an
  `invalidate()` hook) and use it everywhere; or read from
  `request.app.state.config` where a request is available. Low urgency —
  do together with any config-reload feature.

### 2.4 `[ ]` Dual SSE response imports

- **Where:** `app/routers/nfc.py:30-31`, `app/routers/system.py:9-11` — both
  import `EventSourceResponse` from `fastapi.responses` (annotation only) and
  from `sse_starlette` (actual response).
- **Fix:** import once from `sse_starlette` and use it for both annotation
  and construction.

### 2.5 `[ ]` Mixed datetime idioms

- **Where:** `story_manager.py:111` uses `datetime.utcnow().isoformat()+"Z"`;
  the rest uses `datetime.now(timezone.utc).isoformat()`.
- **Fix:** standardize on `datetime.now(timezone.utc)` (utcnow is deprecated
  in newer Pythons anyway).

### 2.6 `[ ]` Non-deterministic SD seed from `hash()`

- **Where:** `generate.py:234`, `gpio_dispatcher.py:196` —
  `hash(story_id) & 0xFFFFFFFF` is randomized per process
  (PYTHONHASHSEED), so "same story → same cover" doesn't survive a restart.
- **Fix:** `zlib.crc32(story_id.encode())` in one shared helper (put it next
  to `cover_prompt_builder.build`).

### 2.7 `[ ]` `cards.py` bypasses the StoryManager lock

- **Where:** `app/routers/cards.py:51` calls `story_manager._load_index()`.
- **Fix:** add `StoryManager.list_cards(type: str | None = None)` holding
  `self._lock`; router uses it.

### 2.8 `[ ]` Lint debt

- `ruff check app`: 11×E501, 1×F401 (`audio_player.py:52` — use
  `importlib.util.find_spec("simpleaudio")`), 1×N806
  (`led_effects.py:157` `_RAINBOW_PERIOD` → lowercase). Tests add ~190 more
  (mostly E501/E741). `update_manager._run_ruff()` runs `ruff check app/` on
  OTA updates — keep `app/` at zero errors or updates will roll back!
  (Today it passes because ruff's default select differs from pyproject's;
  do not rely on that — align and clean.)

## 3. AI generation on the 8 GB Jetson

### 3.1 `[ ]` Shrink llama-server KV cache; try full GPU offload

- **Where:** `deploy/llama-server.service` (`-c 8192 --n-gpu-layers 32`).
- **Rationale:** prompt ≈ 200 tokens, output ≤ 600 → `-c 2048` is plenty and
  frees hundreds of MB of unified RAM; add `-ctk q8_0 -ctv q8_0` to halve the
  rest. With that headroom, try full layer offload (check total layer count
  in the server log at startup) for a tok/s bump.
- **Verify:** `scripts/bench_llm.py` before/after; watch `jtop` RSS.

### 3.2 `[ ]` Handle `finish_reason == "length"` (truncated stories get narrated)

- **Where:** `story_generator.py` ignores `choices[0].finish_reason`;
  `max_tokens=600` can cut mid-sentence and `SentenceBuffer.flush()` will
  narrate the fragment.
- **Fix:** capture `finish_reason` from the final chunk; when it is
  `"length"`, drop the incomplete tail (don't flush it as a sentence) and/or
  log a `story_truncated` event. A story ending one sentence early beats one
  that stops mid-word.

### 3.3 `[ ]` Skip regeneration when a cover already exists

- **Where:** `gpio_dispatcher._generate_cover` /
  `swap_orchestrator.generate_cover_for_story`.
- **Problem:** re-pressing the image button after success regenerates the
  *same image* (seed derived from story_id) through a full llama-stop → SD →
  llama-start cycle.
- **Fix:** before swapping, check
  `content/generated/<story_id>/cover-preview.png` exists → enqueue the
  existing URL + rainbow ack and return.

### 3.4 `[ ]` SD worker: unified memory makes sequential CPU offload a pure cost

- **Where:** `scripts/sd_cover_worker.py:66`
  (`pipe.enable_sequential_cpu_offload()`).
- **Rationale:** on Jetson, CPU and GPU share the same physical RAM —
  per-submodule offload doesn't reduce total pressure, it only adds transfer
  latency. llama-server is stopped during the swap, so ~3+ GB is free.
- **Fix (benchmark ladder, keep the first that fits):**
  1. `pipe.to("cuda")` + `enable_vae_tiling()` + `enable_vae_slicing()`
     (drop `enable_attention_slicing(1)` first; re-add if OOM).
  2. `pipe.enable_model_cpu_offload()` (per-model, far faster than
     sequential).
  3. current `enable_sequential_cpu_offload()` as last resort.
  Use `scripts/bench_sd.py`; watch peak RSS + gen_seconds.

### 3.5 `[ ]` Pre-fuse LoRAs offline to kill the per-cover cold start

- **Where:** `sd_cover_worker.build_pipeline()` loads base + 2 LoRAs and
  fuses **on every button press**.
- **Fix:** one-off script (run on the Jetson or dev machine):
  load pipeline, `load_lora_weights` ×2, `set_adapters`, `fuse_lora`,
  `unload_lora_weights`, then `pipe.save_pretrained(~/sd-cover/models/sd15-storybot-fused, safe_serialization=True)`.
  Worker then does a single `from_pretrained` of the fused checkpoint
  (fp16) — no transformers/peft LoRA work at cover time. Cuts load time and
  peak RAM. Keep `LCMScheduler.from_config` at load.

### 3.6 `[ ]` Verify `WORKER_TIMEOUT_S=120` against on-device p95

- **Where:** `swap_orchestrator.py:22`.
- After 3.4/3.5 this should have huge margin; before them, a cold load that
  exceeds 120 s costs a kill + llama restart for nothing. Measure and set to
  ~2× p95.

## 4. Voice quality: Kyutai pocket-tts (charles, Spanish)

Goal: replace/augment Piper `es_ES-sharvard-medium` with
[kyutai/pocket-tts](https://huggingface.co/kyutai/pocket-tts) using the
Spanish `charles` embedding from
`kyutai/pocket-tts → languages/spanish/embeddings/charles.safetensors`
(6.2 MB; more embeddings in `kyutai/tts-voices`).

Facts (verified 2026-07): 100M params, CPU-first, streaming API, voice
cloning, CC-BY-4.0, `pip install pocket-tts`, PyTorch ≥ 2.5, Python 3.10+.
~6× real-time on 2 cores of an Apple M4, ~200 ms first chunk. Spanish uses
the **undistilled 24-layer** variant — slower than the distilled English.

Risks to measure on the Orin (Cortex-A78AE is much slower than M4):
- RTF for the 24-layer Spanish model on CPU (4-6 threads). Sub-real-time may
  still be OK: the sentence queue masks synthesis after the first sentence.
- RSS: in-process PyTorch ≈ 0.5–1 GB vs Piper's ~400 MB ONNX. Budget it
  together with §3.1's KV-cache savings.
- GPU option: the model is ~300–400 MB — it can run on CUDA next to
  llama-server, but must be released during the SD swap (coordinate with
  SwapOrchestrator, like nothing else currently does for TTS).

Implementation plan:
1. `[ ]` **Prerequisite:** make sample rate part of the synthesizer contract.
   `app/services/tts_pipeline.py:33` hardcodes 22050 Hz — pocket-tts outputs
   a different rate → pitch-shifted playback. Add
   `sample_rate: int` property to `TTSEngine` (22050) and use
   `self._synth.sample_rate` in `TTSPipeline.synthesize_segment`.
   Test first (red): a fake synth with `sample_rate=24000` must produce a WAV
   whose header says 24000.
2. `[ ]` Benchmark script `scripts/bench_pocket_tts.py`: RTF per sentence
   (short/medium/long Spanish), first-chunk latency, RSS before/after load,
   CPU (2/4/6 threads) and CUDA; voices: charles + 2–3 others. Compare Piper.
3. `[ ]` `PocketTTSEngine(HardwareService)` in
   `app/services/pocket_tts_engine.py`: same duck-typed
   `synthesize(text) -> bytes` (PCM int16 mono) + `sample_rate`; embedding
   path configurable; `is_mock=False`, `is_loaded`, `get_status()` like
   `TTSEngine`.
4. `[ ]` Engine selection via config: reuse `tts_voice` (§1.7) or add
   `tts_engine: "piper" | "pocket"`; `HardwareManager.detect_hardware`
   builds the chosen engine, falls back to Piper when pocket-tts import or
   model load fails (never leave AI mode without TTS).
5. `[ ]` A/B with the teachers; keep Piper installed as fallback either way.
6. Cheaper interim option: none worth it — sharvard-medium is already the
   best Castilian Piper voice; es_MX voices exist (e.g. claude-high) but are
   Mexican Spanish.

## 5. Arduino UNO Q (non-AI mode) gaps

- `[ ]` **GPIO buttons dead:** `gpio_handler.py` only has a Jetson.GPIO
  backend; on the Q (aarch64 Debian, no Jetson.GPIO) the factory returns the
  mock → the four physical buttons do nothing. Add a `libgpiod` (or
  `gpiozero` with lgpio) backend selected by platform, same
  `initialize(queue)/run/shutdown/trigger` surface, pins via `Settings`.
- `[ ]` **platform_detect:** knows jetson/rpi/generic only. Add an
  `arduino`/`unoq` marker (check `/proc/device-tree/model` for the QRB2210 /
  "Arduino UNO Q" string) so `/api/system/status` reports honestly and the
  GPIO/LED factories can branch.
- `[ ]` **LED strip:** `led_spi`/spidev is Jetson-tuned (`spidev0.0`,
  6.4 MHz encoding). Verify the Q's SPI node + timing, or gate LED to mock
  with a clear status message.
- `[ ]` **NFC stack:** ensure `libpcsclite1`, `pcscd`, and the ACR122U udev
  rules are in whatever install path the Q uses; without them pyscard import
  fails → silent mock (+ bug 1.3 until fixed).
- `[ ]` **simpleaudio wheel:** needs ALSA headers at build time on the Q's
  Debian — verify install or vendor a wheel.
- `[ ]` **install.sh:** Jetson-shaped (nvpmodel, jetpack, llama, SD). Add a
  `--non-ai` path (skip llama/SD/CUDA steps, skip jetson extras:
  plain `uv sync`).

## 6. Test-infra notes

- The suite takes ~90 s; the SSE/system tests build many app instances.
- `tests/test_basic.py::test_imports` returns bool → PytestReturnNotNone
  warning; use asserts.
- 204 warnings, mostly Pydantic v2 deprecations:
  `config.py` class-based `Config` (→ `ConfigDict`),
  `hardware_manager.py:53` `.dict()` (→ `.model_dump()`).
