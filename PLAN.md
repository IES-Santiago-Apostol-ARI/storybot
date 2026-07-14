# PLAN.md — StoryBot: 7-task batch

Grounded in codebase exploration (2026-07-12). Execute in the order given in
[Execution notes](#execution-notes). Backend tasks follow TDD red/green.

---

## Task 1 — README: llama.cpp build instructions

**File:** `README.md`

Add a `#### Compilar llama.cpp` subsection under
`### Dependencias del sistema (JetPack 6.2.1)` (~L177–214), before
`### Configuración del entorno`. README currently has no llama.cpp build
section — only passing `llama-server` references at L280/292.

Content:

```bash
sudo apt install ccache
```

```bash
cmake -B build \
    -DGGML_CUDA=ON \
    -DCMAKE_CUDA_COMPILER=/usr/local/cuda-12.6/bin/nvcc \
    -DCMAKE_CUDA_ARCHITECTURES="87" \
    -DCMAKE_BUILD_TYPE=Release \
    -DLLAMA_BUILD_TESTS=OFF \
    -DLLAMA_BUILD_EXAMPLES=OFF \
    -DGGML_CUDA_FA_ALL_QUANTS=ON \
    -DGGML_NATIVE=ON

cmake --build build --config Release -j$(nproc)
```

**Verify:** markdown renders correctly; section sits in the Jetson
system-dependencies flow.

---

## Task 2 — config.py: speaking-speed option (1.0 = current speed)

A Piper duration knob already exists end-to-end (`tts_length_scale`,
default 1.2, >1 = slower). The new option layers on top so `1.0` keeps
today's speed exactly.

- `app/config.py` (Settings L9–65): add `tts_speed: float = 1.0`
  (>1 faster, <1 slower). Clamp/fallback to default on invalid values,
  matching the existing invalid-key fallback pattern (L96–101).
- `app/services/hardware_manager.py` L84–94: pass effective
  `length_scale = tts_length_scale / tts_speed` into
  `tts_engine.initialize(...)`.
- Applied at startup like `tts_voice` / `tts_speaker` (no live reload —
  matches existing behavior).

**TDD:** `tests/test_services/test_config.py` (default, fallback on invalid)
and `tests/test_services/test_hardware_manager.py` (effective length_scale
forwarded to `initialize`).

---

## Task 3 — Cap generated stories at 5

New story generation must never leave more than 5 stories in
`content/generated/`; the oldest are deleted to make room. Today only the
7-day age sweeper (`app/services/generated_sweeper.py`) cleans up — no count
cap exists.

- `app/services/story_manager.py`: new `prune_generated(max_count)` —
  sort `list_generated()` (L406) by `created_at`, call `delete_generated()`
  (L436) on the oldest until count ≤ `max_count`.
- `app/routers/generate.py`: constant `MAX_GENERATED_STORIES = 5`; at the
  start of story generation (before `_save_generated_story` L40) call
  `prune_generated(MAX_GENERATED_STORIES - 1)`, so at most 5 exist after
  the new story is saved.
- Scope: `content/generated/` only. Curated `content/stories/` untouched.
  The 7-day sweeper stays as-is.

**TDD:** `tests/test_services/test_story_manager.py` +
`tests/test_api/test_generate.py` (6th generation deletes the oldest).

---

## Task 4 — Audio transcription for /admin uploads (whisper.cpp)

Greenfield — no STT exists anywhere in the repo. Transcript is stored as
story text metadata.

- **Runtime:** whisper.cpp `whisper-cli`, built on the Jetson like
  llama.cpp (CUDA arch 87). Add a `#### Compilar whisper.cpp` README
  subsection next to Task 1's, plus ffmpeg as a system dependency.
  Model: `ggml-small` (~466 MB), language `-l es`. Invoke with GPU off by
  default (`--no-gpu`) — transcription is an occasional admin action and
  must not fight llama-server/SD for the Jetson's unified 8 GB memory.
- **Config** (`app/config.py`): `whisper_bin: str`, `whisper_model: str`,
  `transcription_enabled: bool = True`. Effective only when binary + model
  exist on disk; dev machines fall back to disabled, matching the
  STORYBOT_AI mock pattern.
- **New service** `app/services/transcriber.py`: async
  `transcribe(audio_path) -> str | None` — ffmpeg-convert the upload
  (mp3/wav) to 16 kHz mono WAV in a temp dir, run `whisper-cli`, return
  text. Serialize with an `asyncio.Lock`. On missing binary or failure:
  log and return `None` (the upload itself always succeeds).
- **Model:** add `transcript: str | None = None` to `Story`
  (`app/models/story.py:15`); persist via `story_manager` in `stories.json`.
- **Route** (`app/routers/stories.py`): after `POST /api/stories`
  (`create_story` L75) saves the audio, schedule a background task that
  transcribes and stores the transcript; same on `PUT /api/stories/{id}`
  when the audio file is replaced.

**TDD:** new `tests/test_services/test_transcriber.py` (mocked
ffmpeg/whisper subprocesses) + `tests/test_api/test_stories.py`
(background task fires, transcript persisted, upload unaffected when STT
fails). Never drive real binaries/hardware in tests (repo rule).

---

## Task 5 — GPIO image button: always regenerate, replacing the old image

- `app/services/gpio_dispatcher.py` `_generate_cover` (L188–234): remove
  the "reuse existing cover" branch (L202–206); always generate.
- Use a **random seed** instead of the deterministic
  `cover_prompt_builder.story_seed()` — the seed derives from `story_id`,
  so without this the regenerated image would be pixel-identical (that
  determinism is why the reuse branch exists today).
- The SD worker overwrites `cover-preview.png` / `cover-print.png` in
  `content/generated/<story_id>/`, which replaces the old image. The old
  image survives if generation fails (safer than pre-deleting).
- "Ignore press while generating" already exists — `_image_busy`
  (L167/185/234) plus `SwapOrchestrator._lock` — keep unchanged.

**TDD:** `tests/test_services/test_gpio_dispatcher.py` — press with an
existing cover regenerates; press while busy is ignored; seeds vary
between presses.

---

## Task 6 — Adaptive emoji size on children screen

Few stories → big emoji tiles; many stories → small tiles, with the current
size as the minimum.

- `static/children/script.js` `renderStoryGrid()` (L299–326): compute a
  scale factor from story count vs. available grid space and set a CSS
  custom property (`--card-scale`) on `.story-grid`; recompute on window
  resize. Scale ≥ 1 always (current size is the floor), capped ~2.5×.
- `static/children/styles.css`: `.story-card` (L109–125) width/height and
  emoji `font-size: 4rem` become `calc(base * var(--card-scale, 1))`;
  convert the nth-child pixel size variants (L134–136) to relative
  multipliers so the playful variation scales too.

**Verify:** visually with 1, 5, and 12+ stories in the kiosk.

---

## Task 7 — Double the walking robot's size

- `static/children/index.html` L75: `.progress-character` SVG
  `width="60" height="60"` → `width="120" height="120"` (viewBox unchanged).
- `static/children/script.js` L600: travel math assumes a 60 px sprite
  (`maxX = window.innerWidth - 80`) → adjust to `- 140` so the bigger robot
  doesn't run off-screen.
- `static/children/styles.css` `.progress-track` (L369–376, height 80px):
  bump height so the 120 px robot isn't clipped.

**Verify:** play a story in the kiosk; robot walks the full track at 2×
size without clipping.

---

## Execution notes

- TDD red/green for backend tasks; surgical changes only (CLAUDE.md).
- Run impact analysis (gitnexus/codegraph) before editing symbols, per
  project rules.
- Order: 1 (docs) → 2, 3, 5 (independent backend, TDD) → 4 (largest,
  backend + docs) → 6, 7 (frontend).
- Verification gate: `uv run pytest` (suite must stay 1008/1008 green —
  any failure is a real regression), `uv run ruff check .`,
  `uv run black .`, manual kiosk check for Tasks 6–7, on-Jetson smoke test
  for Tasks 4–5.
- do not commit this file, but update it after tasks are done
