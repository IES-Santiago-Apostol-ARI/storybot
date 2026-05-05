# StoryBot Agent Configuration

## Project Overview

**StoryBot** is a storytelling robot for children ages 3-6, running 100% offline on NVIDIA Jetson Orin Nano Super 8GB. It uses FastAPI, local AI models (Ollama + Piper TTS + Stable Diffusion), NFC cards, and a thermal sticker printer.

## Environments

There are **two distinct environments**. Code is written and tested on the development machine, then deployed to the Jetson.

### Development Machine (where you are running)

- **Architecture**: x86_64
- **OS**: Ubuntu 24.04 LTS (kernel 6.14)
- **Python**: 3.10.18
- **GPU**: NVIDIA RTX 4000 Ada (12GB VRAM)
- **CUDA**: via pip packages (cuda-python, cupy, torch, etc.)
- **Package Manager**: uv

### Target Device (production)

- **Hardware**: NVIDIA Jetson Orin Nano Super 8GB
- **Architecture**: aarch64 (ARM)
- **OS**: Ubuntu 22.04 LTS (Linux 5.15 tegra, JetPack 6.2.1)
- **Python**: 3.10.12
- **CUDA**: 12.6.10 (pre-installed via `nvidia-jetpack` apt package)
- **TensorRT**: 10.3.0 (pre-installed via apt)
- **cuDNN**: 9.3.0 (pre-installed via apt)

### Key difference

On the **dev machine**, CUDA/AI libraries are installed as pip dependencies (see `[project.optional-dependencies] jetson` in pyproject.toml). On the **Jetson**, these same libraries come pre-installed as system packages via `sudo apt install nvidia-jetpack` — they should NOT be pip-installed there. The `jetson` optional dependencies exist to emulate the Jetson environment on x86 for development and testing.

## Project Setup

### Initialize project with uv

```bash
uv venv
uv sync
```

### Install development dependencies

```bash
uv sync --extra dev
```

## Code Standards

### Formatting

- **Black** for code formatting (line length: 88)
- Run formatter: `uv run black .`

### Type Checking

- **Ruff** for linting and import sorting
- Run linter: `uv run ruff check .`
- Run formatter: `uv run ruff format .`

### Testing

- **pytest** for unit and integration tests
- Run tests: `uv run pytest`
- Test coverage: `uv run pytest --cov`

## Project Structure

```
storybot/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI application entry point
│   ├── config.py               # Configuration settings
│   ├── routers/                # API route modules
│   │   ├── __init__.py
│   │   ├── stories.py          # Story CRUD endpoints
│   │   ├── admin.py            # Admin panel endpoints
│   │   ├── generate.py         # AI generation endpoints
│   │   ├── nfc.py              # NFC handling endpoints
│   │   ├── printer.py          # Printer control endpoints
│   │   └── system.py           # System status & LED control
│   ├── services/               # Business logic
│   │   ├── __init__.py
│   │   ├── model_manager.py    # AI model loading/unloading
│   │   ├── story_generator.py  # LLM story generation
│   │   ├── tts_engine.py       # Piper TTS integration
│   │   ├── image_generator.py  # Stable Diffusion pipeline
│   │   ├── nfc_handler.py      # NFC reader/writer
│   │   ├── printer_handler.py  # Brother QL printer
│   │   ├── led_controller.py   # RGB LED control
│   │   ├── audio_player.py     # Audio playback
│   │   └── content_manager.py  # Content storage management
│   └── models/                 # Pydantic schemas
│       ├── __init__.py
│       └── ...
├── static/                     # Frontend assets
│   ├── children/               # Children's UI (kiosk)
│   │   ├── index.html
│   │   ├── styles.css
│   │   └── script.js
│   └── admin/                  # Teacher admin panel
│       ├── index.html
│       ├── styles.css
│       └── script.js
├── content/                    # Story content storage
│   ├── stories/               # Narrated stories (JSON + audio)
│   ├── interactive/          # Interactive story trees (JSON)
│   └── images/                # Pre-generated images
├── models/                     # AI models (managed by Ollama)
├── tests/                     # Test suite
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_api/
│   ├── test_services/
│   └── test_integration/
├── pyproject.toml
├── uv.lock
├── README.md
├── AGENTS.md
└── .gitignore
```

## Key Technical Decisions

### AI Models

- **LLM**: Qwen 2.5 3B Instruct (Q4_K_M) via Ollama - ~2GB RAM, 35-45 tok/s
- **TTS**: Piper TTS with es_ES voices - always loaded, ~400MB RAM
- **Image Generation**: Stable Diffusion 1.5 + LCM LoRA + Lineart LoRA - ~2.8 Memory Management

TheGB RAM

### 8GB RAM is shared between OS, app, and AI models. Models are loaded/unloaded based on active task:
- Piper TTS: always loaded
- LLM and SD: can coexist with Qwen 2.5 3B (~4.8GB combined)

### Real-time Communication

- **Server-Sent Events (SSE)** for streaming AI generation to frontend
- **FastAPI** for REST API serving both children (kiosk) and teachers (mobile)

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/stories` | GET | List all stories |
| `/api/stories` | POST | Upload new story |
| `/api/stories/{id}` | GET | Get story by ID |
| `/api/stories/{id}` | DELETE | Delete story |
| `/api/generate/story` | POST | Generate AI story (SSE) |
| `/api/generate/status/{task_id}` | GET | Generation progress (SSE) |
| `/api/nfc/read` | GET | Read NFC card (SSE) |
| `/api/nfc/write` | POST | Write UID to NFC card |
| `/api/printer/print` | POST | Print sticker |
| `/api/system/status` | GET | System status (RAM, models) |
| `/api/system/led` | POST | Control RGB LEDs |

## Testing Strategy

1. **Unit tests**: Test individual service functions
2. **Integration tests**: Test API endpoints with mocked services
3. **Hardware tests**: Test NFC, printer, LED with actual hardware (optional, can be mocked)

## Common Tasks

### Run development server

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Run tests with coverage

```bash
uv run pytest --cov=app --cov-report=html
```

### Format and lint code

```bash
uv run black .
uv run ruff check . --fix
uv run ruff format .
```

## Hardware Integration

- **NFC Reader**: ACS ACR122U (USB) - uses nfcpy library
- **Printer**: Brother QL-800 - uses brother_ql library
- **LED Strip**: USB-controlled RGB (Govee or similar)
- **Display**: 7" HDMI touchscreen running Chromium kiosk mode
- **Network**: TP-Link TL-WR802N as access point

## Important Notes

- All AI inference runs locally - NO internet required in production
- Teacher panel accessible at `/admin` with HTTP Basic auth
- Children interface runs in Chromium kiosk mode at `http://localhost/`
- Use SSE instead of WebSockets for server-to-client streaming

## Framework Constraints

- Frontend MUST use vanilla JS (no React/Vue/Angular). htmx is allowed

- NEVER EVER COMMIT FILES FROM .planning directory

- Use Test driven development with red/green to create new code

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

##  Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:

- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:

- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **storybot** (2045 symbols, 3710 relationships, 76 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/storybot/context` | Codebase overview, check index freshness |
| `gitnexus://repo/storybot/clusters` | All functional areas |
| `gitnexus://repo/storybot/processes` | All execution flows |
| `gitnexus://repo/storybot/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
