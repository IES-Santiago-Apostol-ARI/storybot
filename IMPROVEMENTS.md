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

### 1.3 `[x]` NFC `stop_polling` signature mismatch crashes SSE cleanup on mock hardware (2026-07-07)

- **Where:** `app/routers/nfc.py:152` calls
  `await nfc_service.stop_polling(card_callback)`;
  `app/services/nfc_handler.py` — `MockNFCService.stop_polling(self)` (~line
  243) takes no argument; the base `NFCService.stop_polling(self)` protocol
  (~line 37) also declares no argument. `RealNFCService.stop_polling(self,
  callback=None)` does.
- **Symptom:** On any device where pyscard fails to import (Arduino UNO Q
  without libpcsclite/pcscd) the factory returns `MockNFCService`; every SSE
  disconnect then raises `TypeError` in the generator's `finally`.
- **Fix (applied):** base protocol and `MockNFCService` now take
  `stop_polling(callback=None)` like Real; the mock keeps a callback list
  (append on `start_polling`, remove one / clear all on `stop_polling`,
  `simulate_tap` fires every registered callback). Pinned by
  `test_mock_stop_polling_accepts_callback_like_real` and
  `test_mock_supports_multiple_subscribers`.

### 1.4 `[x]` LLM stream errors kill the SSE stream and strand the LED in THINKING (2026-07-07)

- **Where:** `app/services/story_generator.py:66-73` (`_fetch_stream` catches
  only `requests.ConnectionError`/`requests.Timeout` — `raise_for_status()`
  raises `requests.HTTPError` which escapes), and
  `app/routers/generate.py` `stream()` (no try/finally around the body).
- **Symptom:** A 4xx/5xx from llama-server (e.g. still warming up right after
  a cover swap) propagates out of `asyncio.to_thread`, aborts the
  StreamingResponse with no `{"error": ...}` event; the animator stays in
  THINKING/PROGRESS. A client disconnect mid-generation (`GeneratorExit`)
  leaves the LED stuck the same way.
- **Fix (applied):** done in two halves together with 1.10:
  1. `StoryGenerator.generate_story` (now httpx-native) catches
     `httpx.HTTPError` — which includes `HTTPStatusError` from
     `raise_for_status()` — and yields the terminal error event, pinned by
     `test_http_status_error_yields_error_event`.
  2. `generate.py` wraps the stream body: `GeneratorExit` (client
     disconnect) → `Mode.IDLE`; unexpected `Exception` → terminal
     `{"error": <type>, "done": true}` event + `Mode.ERROR` (auto-fades,
     D-16). Pinned by `TestGenerateStreamResilience`.

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

### 1.6 `[x]` `hardware.rescan()` leaks live services (duplicate NFC events, double Piper RAM) (2026-07-07)

- **Where:** `app/services/hardware_manager.py:90-97` (`rescan` →
  `detect_hardware` re-registers without shutting down).
- **Symptom:** The old NFC `CardMonitor` observer keeps firing (each tap can
  invoke callbacks registered on the *old* service), and Piper (~400 MB) is
  loaded a second time while the old engine is still referenced — a real
  spike on 8 GB.
- **Fix (applied):** at the top of `detect_hardware`, pop each service about
  to be replaced (`tts`, `nfc`, `led`, `audio`) and `await
  service.shutdown()` (exceptions swallowed — a failing old service must not
  block the rescan); only then create new instances. `gpio` is left alone
  (registered separately by the lifespan). The old LED driver may take a
  tick's write after shutdown until the `/rescan` route re-points the
  animator (CR-02), but the animator loop catches per-tick exceptions.
  Pinned by `TestRescanShutsDownReplacedServices` (spy shutdown awaited,
  gpio untouched, raising shutdown doesn't abort).

### 1.7 `[x]` `tts_voice` config is dead (2026-07-07)

- **Where:** `app/config.py:42` (`tts_voice: "es_ES-glow_tenor"` — a voice
  that doesn't even exist in the download script) vs
  `app/services/tts_engine.py:37` (hardcoded `es_ES-sharvard-medium`),
  `deploy/download-models.sh` (downloads sharvard).
- **Fix (applied):** `TTSEngine.initialize(model_name=...)` now forwards the
  voice to `load_model`; `detect_hardware` passes
  `ConfigManager().load().tts_voice`; config default changed to
  `es_ES-sharvard-medium` so config matches reality. Field kept — it becomes
  the engine/voice selector when the pocket-tts engine lands (§4). Pinned by
  `test_detect_hardware_passes_configured_tts_voice`,
  `test_tts_engine_initialize_passes_model_name`, and
  `test_default_tts_voice_matches_shipped_model`.
- **Addendum (2026-07-07, commit `eb1ac2d`):** this fix was incomplete —
  the **tracked `content/config.json`** also carried `es_ES-glow_tenor`
  and overrides the Settings default at startup, so fresh installs still
  had no TTS voice ("Model not loaded" on every `audio_ready`). Found by
  driving the live generation flow; config.json now ships sharvard.
  Lesson: changing a `Settings` default requires checking the tracked
  config.json (and deployed devices' saved configs) too.

### 1.8 `[x]` GPIO docstring contradicts code; Jetson.GPIO ignores pull configuration (2026-07-07)

- **Where:** `app/services/gpio_handler.py` class docstring ("internal
  pull-up and falling-edge") vs code `PUD_DOWN` + `GPIO.RISING` (~lines
  105-113).
- **Fix (applied):** docstring now says "pull-down + rising edge (button ties
  pin to 3.3 V)" and warns that Jetson.GPIO **ignores** `pull_up_down` (pulls
  come from pinmux/jetson-io) — external pull-downs required or floating
  inputs will produce phantom presses; same note as a comment at the
  `GPIO.setup` call. `gpio_usage.md` wiring notes (PUD_UP/GND/press=LOW)
  updated to match the shipped pull-down/3.3 V/rising design. Docs-only, no
  behavior change, no test.

### 1.9 `[x]` Hardcoded `/home/ari` in swap orchestrator (2026-07-07)

- **Where:** `app/services/swap_orchestrator.py:12`
  (`SD_VENV_PYTHON = Path("/home/ari/sd-cover/.venv/bin/python")`) —
  inconsistent with `Path.home() / "sd-cover/..."` used in
  `cover_prompt_builder.py:22` and `scripts/sd_cover_worker.py:23-25`.
- **Symptom:** any Jetson whose user isn't `ari` fails every cover *after*
  paying the llama stop/start cycle.
- **Fix (applied):** `SD_VENV_PYTHON = Path.home() / "sd-cover/.venv/bin/python"`.
  Pinned by `TestSdVenvPython::test_sd_venv_python_derives_from_home`.
  Not made a `Settings` field — the other two sd-cover paths aren't either;
  promote all three together if it's ever needed.

### 1.10 `[x]` `requests` is a runtime import but only a dev dependency (2026-07-07)

- **Where:** `app/services/story_generator.py:9`; `pyproject.toml`
  `[dependency-groups].dev` contains `requests`.
- **Symptom:** `uv sync --no-dev` (natural prod invocation) removes requests →
  story generation import error.
- **Fix (applied):** rewrote `StoryGenerator.generate_story` on
  `httpx.AsyncClient` streaming (already a core dep). Removes the
  thread+queue bridge and the hidden `self._params` shared state (pinned by
  `test_concurrent_generations_do_not_share_state`); `httpx.Timeout(timeout,
  connect=5.0)` fails fast on an unreachable server. An injectable
  `transport=` seam keeps tests off the network (`httpx.MockTransport`).
  `requests` stays in the dev group only; nothing in `app/` imports it now.

### 1.11 `[x]` `_strip_think_tags` is ineffective for streamed tags (2026-07-07)

- **Where:** `app/services/story_generator.py:44-50`.
- **Detail:** tags split across deltas never match (each delta is processed
  independently), and the `r"<think\b.*?</think\b"` regex leaves a stray `>`
  even on a whole-tag match. Moot in production because
  `deploy/llama-server.service` runs `--reasoning off --reasoning-format
  none`, but as written it's dead-ish, misleading code.
- **Fix (applied):** deleted (the surgical option) — deltas now pass through
  unfiltered, with a comment in `generate_story` pointing at the
  llama-server.service flags and at why a per-delta filter can't work.
  Removed the tests that pinned the old behavior (`TestStripThinkTags`,
  `test_strips_think_tags_from_chunks`); pass-through is already pinned by
  `test_streams_text`.

## 2. Duplicated / unneeded code

### 2.1 `[x]` `audio_ready` synthesis block duplicated verbatim in generate.py (2026-07-07)

- **Where:** `app/routers/generate.py` — main loop (~127-171) and flush
  (~184-220) are the same ~35 lines.
- **Fix (applied):** extracted a local closure
  `_synth_and_events(sentence)` inside `_stream_body` (uses
  `nonlocal seg_index`; closes over tts_pipeline/animator/story_id/segments)
  that synthesizes one sentence, appends to `segments`, yields the SSE
  strings and drives the LED progress/error modes. Both call sites now
  `async for chunk in _synth_and_events(sentence): yield chunk`. Behavior
  byte-identical — pinned by the existing event-shape tests in
  `tests/test_api/test_generate.py` (all green).

### 2.2 `[x]` `_hex_to_rgb` implemented three times (2026-07-07)

- **Where:** `app/routers/generate.py:31`, `app/routers/system.py:95`,
  `app/services/led_animator.py:62`.
- **Fix (applied):** single `hex_to_rgb` in `app/services/led_effects.py`;
  all three modules import it (no router-into-router imports). No aliases
  needed — no test imported the old names (`test_generate.py` keeps its own
  local copy on purpose). Pinned by `TestHexToRgb` in
  `tests/test_services/test_led_effects.py`, including an identity check
  that all three users share the led_effects implementation.

### 2.3 `[x]` Five module-level `ConfigManager().load()` singletons (2026-07-12)

- **Where:** `generate.py:28`, `gpio_handler.py:14`, `gpio_dispatcher.py:31`,
  `system_control.py:15`, `led_animator.py:54` — plus a sixth the review
  missed: `led_controller.py:12`.
- **Fix (applied):** `app/config.py` now exposes a process-wide shared
  manager: `get_config_manager()` / `get_settings()` (cached) /
  `invalidate_settings()`. `app.state.config` in the lifespan IS the shared
  manager, so a future admin `reload()`/`save()` on it propagates to every
  `get_settings()` caller. All six modules read via `get_settings()` at use
  time (no import-time copies). `deploy/led_selftest.py` keeps its own copy
  on purpose (standalone diagnostic, bypasses the app). Pinned by
  `TestGetSettings` + `TestNoModuleSettingsSingletons` in
  `tests/test_services/test_config.py`.

### 2.4 `[x]` Dual SSE response imports (2026-07-07)

- **Where:** `app/routers/nfc.py:30-31`, `app/routers/system.py:9-11` — both
  import `EventSourceResponse` from `fastapi.responses` (annotation only) and
  from `sse_starlette` (actual response).
- **Fix (applied):** single `from sse_starlette import EventSourceResponse`
  in both routers, used for annotation and construction; the
  `fastapi.responses` import and the `SSEStarletteResponse` alias are gone.
  Pinned by the existing SSE route tests (no new test — import-only).

### 2.5 `[x]` Mixed datetime idioms (2026-07-07)

- **Where:** `story_manager.py:111` uses `datetime.utcnow().isoformat()+"Z"`;
  the rest uses `datetime.now(timezone.utc).isoformat()`.
- **Fix (applied):** `create_story` now uses
  `datetime.now(timezone.utc).isoformat()`. Note the stored suffix changes
  from `Z` to `+00:00` — `Story.created_at` is a plain str and nothing in
  app/ or the frontends parses it, so no consumer change. Pinned by
  `TestCreatedAtTimestamp::test_created_at_is_timezone_aware_utc`
  (`datetime.fromisoformat` rejects the old `Z` form on Python 3.10).

### 2.6 `[x]` Non-deterministic SD seed from `hash()` (2026-07-07)

- **Where:** `generate.py:234`, `gpio_dispatcher.py:196` —
  `hash(story_id) & 0xFFFFFFFF` is randomized per process
  (PYTHONHASHSEED), so "same story → same cover" doesn't survive a restart.
- **Fix (applied):** `cover_prompt_builder.story_seed(story_id)` =
  `zlib.crc32(story_id.encode())`; both call sites use it. Pinned by
  `TestStorySeed` (helper), a crc32 assertion in
  `test_image_success_enqueues_event_and_rainbow_ack` (dispatcher path),
  and `test_seed_is_deterministic_crc32_of_story_id` (kiosk route).
  Existing covers keep their old hash()-seeded images; only future
  regenerations change seed (and 3.3 reuses existing covers anyway).

### 2.7 `[x]` `cards.py` bypasses the StoryManager lock (2026-07-07)

- **Where:** `app/routers/cards.py:51` calls `story_manager._load_index()`.
- **Fix (applied):** `StoryManager.list_cards(type: str | None = None)`
  loads the index under `self._lock` (filtering happens outside the lock);
  the router calls it and no longer touches `_load_index`. Pinned by
  `TestListCards` (returns all / filters by type / empty index, plus a
  source check that the router no longer references `_load_index`).

### 2.8 `[x]` Lint debt (2026-07-07)

- `ruff check app`: 11×E501, 1×F401 (`audio_player.py:52` — use
  `importlib.util.find_spec("simpleaudio")`), 1×N806
  (`led_effects.py:157` `_RAINBOW_PERIOD` → lowercase). Tests add ~190 more
  (mostly E501/E741). `update_manager._run_ruff()` runs `ruff check app/` on
  OTA updates — keep `app/` at zero errors or updates will roll back!
  (Today it passes because ruff's default select differs from pyproject's;
  do not rely on that — align and clean.)
- **Fix (applied):** `app/` is now at zero under the pyproject select
  (E, F, I, N, W, UP) — the OTA gate passes under both configs. E501s: split
  the `SYSTEM_PREAMBLE` strings via implicit concatenation (content
  byte-identical, pinned by `TestSystemPreamble`), wrapped long
  comments/fields in `main.py`, `wifi.py`, `bt_monitor.py`,
  `led_animator.py`. F401: `_check_availability` uses
  `importlib.util.find_spec("simpleaudio")` (note: no longer catches an
  OSError from a broken ALSA at import time — only detects the package;
  `play()` still imports for real). N806: `_RAINBOW_PERIOD` → local
  `rainbow_period`. Left alone: test-tree lint debt (~190) and pre-existing
  black-format debt in 9 untouched `app/` files (`black --check app` still
  fails; separate cleanup — OTA only gates on ruff).

## 3. AI generation on the 8 GB Jetson

### 3.1 `[x]` Shrink llama-server KV cache; try full GPU offload (2026-07-12)

- **Where:** `deploy/llama-server.service` (`-c 8192 --n-gpu-layers 32`).
- **Fix (applied, commit `f3c18f3`):** `-c 2048 --n-gpu-layers 99` in the repo
  template and the live unit. KV cache 256→64 MiB (−192 MiB unified RAM),
  33/33 layers on GPU, graph splits 4→2. Bench (on-device, word-rate — real
  tok/s ≈ 1.5–1.8×): 3.99 → 4.33 w/s at 15W (+8.5%). `-ctk/-ctv q8_0`
  skipped: at `-c 2048` it only saves another 32 MiB — not worth the risk.
- **Note:** decode is memory-bandwidth bound, so the big win came from §3.7
  (25W Super: EMC 2133→3199 MHz): **8.05 w/s mean** (~12–14 tok/s real),
  first-token p50 441 ms (`bench-llm-super.jsonl`, 2026-07-12). The old
  "35–45 tok/s" figure in CLAUDE.md was for Qwen 2.5 3B, not this 4B model.

### 3.2 `[x]` Handle `finish_reason == "length"` (truncated stories get narrated) (2026-07-07)

- **Where:** `story_generator.py` ignores `choices[0].finish_reason`;
  `max_tokens=600` can cut mid-sentence and `SentenceBuffer.flush()` will
  narrate the fragment.
- **Fix (applied):** `generate_story` captures `finish_reason` from the
  stream; on `"length"` the terminal sentinel becomes
  `{"text": null, "done": true, "truncated": true}` (normal completions keep
  the exact legacy shape). `generate.py` then drops the flush-tail fragment
  instead of narrating it, trims it from the saved `story.json` text (an
  all-fragment story saves nothing), and logs a `story_truncated` stderr
  event. Untruncated flush behavior unchanged. Pinned by
  `test_length_finish_reason_marks_sentinel_truncated`,
  `test_stop_finish_reason_keeps_plain_sentinel`, and
  `TestGenerateTruncatedStory` (3 route-level tests).

### 3.3 `[x]` Skip regeneration when a cover already exists (2026-07-07)

- **Where:** `gpio_dispatcher._generate_cover` /
  `swap_orchestrator.generate_cover_for_story`.
- **Problem:** re-pressing the image button after success regenerates the
  *same image* (seed derived from story_id) through a full llama-stop → SD →
  llama-start cycle.
- **Fix (applied):** `gpio_dispatcher._generate_cover` checks
  `GENERATED_DIR / story_id / "cover-preview.png"` (new module constant,
  test seam) before touching the orchestrator; if it exists it logs
  `cover_reused_existing` and falls through to the shared success tail
  (enqueue URL + rainbow ack). The kiosk route (`generate.py`) was left
  alone — its story_id is a fresh uuid, a cover can never pre-exist there.
  Pinned by `test_image_reuses_existing_cover_without_swap` (also asserts
  the busy guard resets).

### 3.4 `[x]` SD worker: unified memory makes sequential CPU offload a pure cost (2026-07-12)

- **Where:** `scripts/sd_cover_worker.py:66`
  (`pipe.enable_sequential_cpu_offload()`).
- **Fix (applied, commit `22cbcd2`):** benchmarked the full ladder on-device
  (llama stopped, production params): tier 1 `pipe.to("cuda")` **OOMs**
  (`NvMapMemAllocInternalTagged error 12`) even with VAE tiling/slicing;
  tier 2 `enable_model_cpu_offload()` 19.3 s/image vs tier 3 sequential
  31.5 s (**~39% faster**). Shipped tier 2; worker verified end-to-end
  (valid line-art output).

### 3.5 `[x]` Pre-fuse LoRAs offline to kill the per-cover cold start (2026-07-12)

- **Where:** `sd_cover_worker.build_pipeline()` loads base + 2 LoRAs and
  fuses **on every button press**.
- **Fix (applied):** `scripts/fuse_sd_loras.py` (one-off, CPU-only so it can
  run next to a live llama-server; idempotent) writes
  `~/sd-cover/models/sd15-storybot-fused` (fp16 safetensors). The worker
  loads the fused checkpoint when present and keeps the legacy
  load+fuse path as fallback. `LCMScheduler.from_config` stays at load.
- **Measured (on-device):** full cold worker run 64 s → **22.6 s** wall
  (gen_seconds 20.75; diffusion itself 9 s — also boosted by §3.7's
  918 MHz GPU). Fused checkpoint generated on the Jetson 2026-07-12.

### 3.6 `[x]` Verify `WORKER_TIMEOUT_S=120` against on-device p95 (2026-07-12)

- **Where:** `swap_orchestrator.py:22`.
- **Fix (applied):** measured cold run after 3.4+3.5+3.7 is 23 s →
  `WORKER_TIMEOUT_S = 60` (~2.6× cold; the old 120 s wasted a full extra
  minute before the kill + llama restart on a hung worker). Tests
  monkeypatch the constant, so no test churn.

### 3.7 `[x]` 25W Super power mode + persistent jetson_clocks (2026-07-12)

- **Not in the original review** — found while doing 3.1 on-device: the GPU
  idled at 306 MHz, jetson_clocks didn't survive reboots, and the device ran
  the plain-devkit 15W profile.
- **Fix (applied, commit `60ab68d`):** three layers were needed on this
  OTA-upgraded devkit (see `deploy/enable-super-firmware.sh` header and
  memory for the full story):
  1. Kernel super DTB via `extlinux.conf` FDT (install.sh Step 1f) — a
     `_super` nvpmodel symlink alone is force-reverted by nvpower.sh every
     boot.
  2. `deploy/jetson-clocks.service` — oneshot after nvpmodel, re-pins
     clocks at boot.
  3. One-time QSPI migration (`deploy/enable-super-firmware.sh`): OTA
     capsules are chosen by the flash-time identity in
     `/etc/nv_boot_control.conf`, so the device kept getting non-super
     firmware with BPMP-clamped tables. install.sh only detects
     (emc max_rate / nvpmodel -q) and prints a capital warning.
- **Result:** EMC 2133→3199 MHz, GPU 624→918 MHz, 25W persists across
  reboots. LLM decode 4.33→8.05 w/s (+86%); SD diffusion 19.3→9 s.
  Warning: 25W draws more power/heat — watch thermals in the enclosure.

## 4. Voice quality: Kyutai pocket-tts (charles, Spanish) — DROPPED 2026-07-07

**Decision:** ear test done (see "Measured" below) — the native-source
pocket-tts voices (lola, rafael) sound Hispanic-American, not Castilian,
and the Jetson-viable variant was already marginal on RAM. Staying with
Piper. Samples: `~/pocket-tts-eartest/wavs/piper-sharvard-{male,female}/`.

**Follow-up shipped (2026-07-07, commit `1c9d2a2`):**
`es_ES-sharvard-medium` is a 2-speaker model (`{M: 0, F: 1}`); the app now
picks a speaker **randomly per story** (children don't know who will
narrate) and holds it across all segments, via `Settings.tts_speaker`
("random" | "M" | "F", default random). Speech slowed for ages 3-6 via
`Settings.tts_length_scale` (piper duration multiplier, default 1.2).
Pinned by `TestSpeakerAndRate`, `TestSpeakerForwarding`,
`TestStorySpeakerConsistency`, and the extended detect_hardware test.
Verified end-to-end on the dev machine against the live SSE API with real
Piper (recipe persisted in `.claude/skills/verify/SKILL.md`, git-ignored).

Goal: replace/augment Piper `es_ES-sharvard-medium` with
[kyutai/pocket-tts](https://huggingface.co/kyutai/pocket-tts) using the
Spanish `charles` embedding from
`kyutai/pocket-tts → languages/spanish/embeddings/charles.safetensors`
(6.2 MB; more embeddings in `kyutai/tts-voices`).

Facts (verified 2026-07): 100M params, CPU-first, streaming API, voice
cloning, CC-BY-4.0, `pip install pocket-tts`, PyTorch ≥ 2.5, Python 3.10+.
~6× real-time on 2 cores of an Apple M4, ~200 ms first chunk. Spanish uses
the **undistilled 24-layer** variant — slower than the distilled English.

**Measured 2026-07-07 (dev machine, CPU-only, 6 threads, torch 2.12 cpu;
ear-test WAVs + scripts in `~/pocket-tts-eartest/`, results JSONs in
`~/pocket-tts-eartest/wavs/`):**

| variant | load | RSS after load | peak RSS | RTF x86 | first chunk |
|---|---|---|---|---|---|
| piper sharvard (baseline) | 0.4 s | ~165 MB | ~317 MB | 0.02–0.03 | — |
| spanish (distilled 6l) | 0.6 s | 762 MB | 1032 MB | 0.20 | 0.07 s |
| spanish + int8 quantize | 1.0 s | 784 MB | 958 MB | 0.12–0.17 | 0.04 s |
| spanish_24l | 54 s | 2377 MB | 2724 MB | 0.54–0.73 | 0.23 s |
| spanish_24l + int8 | 3.0 s | 1494 MB | 2286 MB | 0.31–0.40 | 0.12 s |

- **spanish_24l is not viable on the 8 GB Orin** (2.3–2.7 GB in-process next
  to llama-server; RTF would be >1 on Cortex-A78AE). The distilled `spanish`
  config (a 2026 addition — the old "Spanish is 24l-only" fact is outdated)
  with `quantize=True` is the only candidate: <1 GB peak, x86 RTF ~0.13 →
  est. 0.4–0.7 on the Orin. Still ~2–3× Piper's RAM.
- **Gated repo:** `kyutai/pocket-tts` needs HF login + accepted terms; the
  library silently falls back to public
  `kyutai/pocket-tts-without-voice-cloning` (catalog voices only, no
  cloning). Pass bare catalog names (e.g. `"lola"`) to
  `get_state_for_audio_prompt` — a `languages/.../x.safetensors` URL 401s.
- **Voice provenance:** most Spanish catalog voices are cross-lingual clones
  of English speakers (charles = VCTK p254!). Native-Spanish sources:
  `lola` (Common Voice es). `rafael` unclear. Ear-test accordingly.
- **Generation instability observed:** distilled `charles/media` collapsed
  to 0.4 s (early EOS); `lola/corta` ran 9 s for a 3.5 s sentence. Piper
  never does this — any integration needs a duration sanity check + retry.

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

- `[x]` `tests/test_basic.py::test_imports` returned bool (and its body was
  vacuous — the try block only printed). Rewritten to import `app.main` and
  assert on `app` (2026-07-07).
- `[x]` Pydantic v2 deprecations — **suite now runs with 0 warnings** (was
  ~204/208): `config.py` `class Config` → `model_config =
  ConfigDict(validate_default=True)` (the `json_encoders = {Path: str}` was
  dropped: no Path-typed field exists and `save()` uses `model_dump_json`);
  `hardware_manager.py:53` and `test_lifespan.py:188` `.dict()` →
  `.model_dump()` (2026-07-07).
- `[x]` The API test fixtures write through the real `GENERATED_DIR` (2026-07-12).
  Root cause was worse than the symptom: lifespan tests running with the
  device's `.env` (`STORYBOT_AI=1`) install a REAL `SwapOrchestrator` on the
  module-level `app`, and `app.state` is never wiped between tests — later
  tests posting `/api/generate/story` (mock LLM/TTS, unmocked orchestrator)
  drove the real `sudo systemctl stop llama-server` + SD-worker cycle:
  22 llama restarts + 11 real covers in ONE partial run on the Jetson
  (`test_generate.py` alone took 390 s because of it). **Fix:** root-conftest
  autouse fixture `_isolate_generated_dir_and_swap` points
  `generate.GENERATED_DIR` / `gpio_dispatcher.GENERATED_DIR` at `tmp_path`
  and stubs `SwapOrchestrator.generate_cover_for_story` /
  `ensure_llama_running` for every test except `test_swap_orchestrator.py`
  (which tests the real methods over mocked subprocesses). Measured:
  `test_generate.py` 390 s → 3.1 s, zero leaked dirs, zero llama restarts.
- `[x]` Suite hotspots (2026-07-12): `test_api_capability_parity.py` now
  starts ONE lifespan per AI branch for the whole module (module-scoped
  `branch_statuses` fixture) instead of two per parametrized route
  (12 → 2 startups); `test_swap_orchestrator.py` gets an autouse
  `MEM_SETTLE_S = 0` (the 3 s settle sleep ran even with subprocesses
  mocked). Also fixed en passant: the parity assert's message was a
  truncated no-op f-string statement.
