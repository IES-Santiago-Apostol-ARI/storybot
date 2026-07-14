# Plan: Jetson Orin Nano GPIO Pushbutton Integration

## Context

StoryBot runs offline on a Jetson Orin Nano Super (kiosk for children). Today all
interaction is via NFC cards + the on-screen UI. We want four physical pushbuttons
wired to the J2 40-pin header so a teacher can operate the device without the app:
power it off, interrupt a playing story, generate an on-screen image from the current
story, and trigger an LED-strip animation.

The codebase already has a clean hardware-service pattern (`HardwareService` protocol +
`Mock`/`Real` implementations, a `HardwareManager`, a FastAPI lifespan, SSE for
server→client events, and an existing `LEDService`). We will follow those patterns so
GPIO slots in like every other peripheral rather than introducing a new paradigm.

### Confirmed decisions
- **4 buttons = 4 actions** (image-gen and LED animation are separate buttons).
- **Image source:** the *parameters* of the currently-playing story, via the existing
  `cover_prompt_builder` + image-generator pipeline (no new "raw text" path).
- **Image output:** show on the kiosk screen (not print).
- **Power off:** `sudo /sbin/poweroff` gated by a passwordless sudoers rule.

### Pin mapping (Jetson.GPIO `BOARD` mode = physical J2 pin number)
| Button | GPIO name | J2 pin | Action |
|--------|-----------|--------|--------|
| Power off      | GPIO09 | 7  | Power off the Jetson |
| Interrupt story | GPIO12 | 15 | Stop audio + send frontend to home (IDLE) |
| Generate image | GPIO01 | 29 | Generate image from current story params → show on kiosk |
| LED animation  | GPIO11 | 31 | Play a predefined LED-strip animation |

`Jetson.GPIO` supports the Orin Nano dev kit and uses physical pin numbers in `BOARD`
mode, so these numbers are used verbatim.

---

## Architecture

A new **GPIO button service** follows the existing `nfc_handler` / `bt_monitor` pattern:
a `HardwareService` with `Mock`/`Real` implementations, a background async polling loop
registered in `app/main.py` lifespan, and handlers that call into existing services.
Buttons are read-only inputs, so the service emits app-level events rather than exposing
REST endpoints of its own (with one exception: a tiny `POST /api/system/poweroff` for the
sudo call, isolated for testability and sudoers-scoping).

Two new server→client event channels reuse the existing SSE approach so the kiosk can
react to physical buttons:
1. **Interrupt** → frontend transitions to `IDLE` (home).
2. **Image-ready** → frontend shows the generated image.

A small **LED animation** method is added to the existing `LEDService` (the controller
currently only has `set_color`; "animation" = a coroutine that drives `set_color`
over time, cancellable).

### State the buttons need (currently missing)
- **Current story params.** The audio player (`app/services/audio_player.py`) is
  file-based and tracks no story metadata. The frontend drives playback via
  `transitionTo(PLAYING, story)`. We track the "currently playing story" server-side
  in a tiny `PlaybackState` holder populated when playback starts (the frontend already
  POSTs the story to play; we piggy-back there) and cleared on stop. This lets the
  image button know which story to render.
- **Interrupt/animation coordination** via `asyncio.Event` + an `asyncio.Queue` of
  SSE events, mirroring how NFC events are streamed today.

---

## Implementation steps (TDD red/green per CLAUDE.md)

### 1. Dependencies & config
- **`pyproject.toml`** — add to the `jetson` extra (aarch64-only, like `spidev`):
  `"Jetson.GPIO>=2.1.0; platform_machine=='aarch64'"`.
- **`app/config.py`** (`Settings` model) — add fields with the BOARD pin numbers above:
  - `gpio_power_pin: int = 7`, `gpio_interrupt_pin: int = 15`,
    `gpio_image_pin: int = 29`, `gpio_animation_pin: int = 31`
  - `gpio_debounce_ms: int = 50`, `gpio_poll_interval_s: float = 0.02`
  - `poweroff_cmd: list[str] = ["/usr/bin/sudo", "/sbin/poweroff"]`
  - `gpio_enabled: bool = True` (set `False` when no hardware / in tests via `TESTING`).
- **Tests first** (`tests/test_services/test_gpio_config.py`): assert defaults exist and
  stale-default-removal style tests matching the existing `test_led_config.py` pattern.

### 2. LED animation support
- **`app/services/led_controller.py`** — add `async def animate(self, name: str) -> None`
  to the `LEDService` protocol and both `RealLEDService`/`MockLEDService`. Implement a
  small registry of named effects (e.g. `pulse`, `rainbow`, `flash`) as coroutines that
  loop `set_color` with `asyncio.sleep` until cancelled. Add `stop_animation()` /
  guard so a new animation cancels any running one. Mock records the last animation name.
- **Tests** (`tests/test_services/test_led.py` — already modified in working tree):
  assert `MockLEDService.animate("pulse")` sets state, `stop_animation` cancels.

### 3. GPIO button service (new file)
- **`app/services/gpio_handler.py`** — `GPIOButtonService(HardwareService)`:
  - `RealGPIOButtonService`: imports `Jetson.GPIO` lazily inside `__init__`;
    `GPIO.setmode(GPIO.BOARD)`; configures the 4 pins as `IN` with `PUD_UP` (buttons
    to GND) and `bouncetime` debounce via edge detection in a worker **thread**
    (`Jetson.GPIO`'s `add_event_detect` runs callbacks on its own thread — we bridge to
    the asyncio loop with `loop.call_soon_threadsafe` / an `asyncio.Queue`). This is
    more reliable than 20 ms polling and matches the push-based `nfc_handler` philosophy.
  - `MockGPIOButtonService`: exposes a `trigger(name)` test seam so tests can inject
    "button presses" without hardware. Records calls; `is_mock` True.
  - Each button maps to a handler method: `_on_power`, `_on_interrupt`, `_on_image`,
    `_on_animation`. Debounce guards prevent repeat-fire.
  - Factory `create_gpio_service()` mirrors `create_led_service()`: returns Mock when
    `TESTING` set or when `Jetson.GPIO` import / pin access fails on non-aarch64.

### 4. Action handlers — wiring to existing services
- **Power off** → call `subprocess.run(settings.poweroff_cmd)`. Isolate behind
  `app/services/gpio_handler.py`'s `_on_power` (which calls a thin
  `system_control.poweroff()` helper) so it can be unit-tested by monkeypatching.
- **Interrupt** → `audio_player.stop()` + put an `{"type": "interrupt"}` event on the
  SSE event queue + clear `PlaybackState`.
- **Generate image** → read current story params from `PlaybackState`; build the prompt
  with the existing `cover_prompt_builder.build(params)`; call the existing image
  generator (same call the `SwapOrchestrator` uses in `app/routers/generate.py`); on
  success, enqueue `{"type": "image", "url": ...}` for the kiosk and play the LED
  animation as feedback. Guard: if nothing is playing, fire a short error LED blink
  and no-op.
- **LED animation** → `led_service.animate(name)` directly.

### 5. Kiosk event channel (SSE) + image display
- **`app/routers/system.py`** — add `GET /api/system/events` SSE stream that drains the
  shared event queue (interrupt + image-ready). Add `POST /api/system/poweroff`
  (delegates to `system_control.poweroff()`; same sudo path) so power-off is also
  reachable from the admin panel.
- **`static/children/script.js`** — open an `EventSource('/api/system/events')` at
  startup; on `interrupt` → call the existing `transitionTo(STATES.IDLE)`; on `image`
  → show the image in a modal/overlay (reuse existing overlay markup style). When the
  user starts playback, ensure the current story is POSTed so `PlaybackState` is set
  (extend the existing play request, no new endpoint needed).

### 6. Lifecycle wiring
- **`app/main.py`** lifespan — register the GPIO service via `HardwareManager` and
  start its background task the same way `bt_monitor_task` is created/cancelled
  (around lines 198 / 211-213). Instantiate the shared event queue + `PlaybackState`
  on `app.state` so routers and the GPIO service share them.

### 7. Jetson device setup (documented, not code)
Add a short **`HARDWARE_GPIO.md`** note (NOT in `.planning`) covering:
- Pinmux: run `sudo /opt/nvidia/jetson-io/jetson-io.py` to set pins 7/15/29/31 to GPIO,
  reboot.
- Permissions: add the app user to the `gpio` group (or the udev rule Jetson.GPIO ships).
- Sudoers: `/etc/sudoers.d/storybot-poweroff` →
  `storybot ALL=(root) NOPASSWD: /sbin/poweroff` (only that exact command — least privilege).
- Wiring: each button between its GPIO pin and GND (internal pull-up enabled → press = LOW).

---

## Critical files
- **New:** `app/services/gpio_handler.py`, `app/services/system_control.py`,
  `tests/test_services/test_gpio_handler.py`, `tests/test_services/test_gpio_config.py`,
  `HARDWARE_GPIO.md`.
- **Edit:** `app/services/led_controller.py` (add `animate`/`stop_animation`),
  `app/config.py` (GPIO fields), `pyproject.toml` (Jetson.GPIO dep),
  `app/routers/system.py` (SSE events + poweroff endpoint),
  `app/main.py` (lifespan registration + shared state), `static/children/script.js`
  (EventSource + image overlay + report current story).

## Reused utilities (no reinvention)
- `cover_prompt_builder.build()` (`app/services/cover_prompt_builder.py`) — image prompt.
- Image-generator call path used in `app/routers/generate.py:151-190`.
- `HardwareService` protocol + `HardwareManager` + lifespan task pattern (`app/main.py`).
- `MockLEDService`/`TESTING`-driven factory pattern from `led_controller.py`.
- Existing `transitionTo(STATES.IDLE)` + overlay markup in `static/children/script.js`.
- `AudioPlayer.stop()` for interruption.

## Verification
1. **Unit (red→green):** `uv run pytest tests/test_services/test_gpio_config.py
   tests/test_services/test_gpio_handler.py tests/test_services/test_led.py` — config
   defaults, mock button triggers fire correct handlers (power monkeypatched,
   interrupt stops mock audio + enqueues event, image calls prompt builder, animation
   sets LED mock state), LED animation start/stop.
2. **Lint/format:** `uv run black . && uv run ruff check .`.
3. **App smoke (dev, no hardware → Mock services):**
   `uv run uvicorn app.main:app --reload`; open the kiosk page; with `TESTING` forcing
   mocks, call `MockGPIOButtonService.trigger("interrupt")` via a debug route or test
   fixture and confirm the kiosk returns home; `trigger("image")` shows the overlay;
   `trigger("animation")` drives the mock LED.
4. **SSE check:** `curl -N http://localhost:8000/api/system/events` stays open and emits
   events when buttons are triggered.
5. **On Jetson (after deploy):** wire buttons, run `jetson-io`, add sudoers rule; press
   each button and confirm power-off, story interrupt, on-screen image, and live LED
   animation. Confirm a clean shutdown leaves no orphaned processes.

## Risks / notes
- **GPIO backend:** on JetPack 6.2.1, `Jetson.GPIO` may use the `gpiod` backend; the
  `add_event_detect` callback-on-thread model still holds — verified during step 3.
- **Power-off needs root:** scoped to exactly `/sbin/poweroff` via sudoers; the app
  never gains broader sudo.
- **Surgical:** no refactor of the audio/image pipelines — we only read existing
  services and add one new method to `LEDService`.

## References
- [jetson-gpio (NVIDIA)](https://github.com/NVIDIA/jetson-gpio)
- [Orin Nano GPIO header pinout (JetsonHacks)](https://jetsonhacks.com/nvidia-jetson-orin-nano-gpio-header-pinout/)
- [Using GPIO pins on Orin Nano (NVIDIA forums)](https://forums.developer.nvidia.com/t/using-gpio-pins-on-orin-nano/364930)
