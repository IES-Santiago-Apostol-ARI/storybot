# Requirements: StoryBot — v1.7 GPIO Pushbuttons

**Defined:** 2026-06-22
**Core Value:** Children can hear AI-generated personalized stories and stories recorded by their teachers on demand.

## v1.7 Requirements

Four physical pushbuttons on the Jetson J2 40-pin header let a teacher operate StoryBot without the touchscreen. Source of truth: `gpio_usage.md` (confirmed decisions). Phases continue numbering from v1.6 (start at Phase 35).

### GPIO Button Service

- [x] **GPIO-01**: GPIO button service follows the existing `HardwareService` Mock/Real pattern, with a `create_gpio_service()` factory returning the mock under `TESTING` or when `Jetson.GPIO` import / pin access fails (non-aarch64)
- [x] **GPIO-02**: Real service configures the 4 BOARD-mode pins as inputs with internal pull-up and debounce, bridging edge-detect callbacks to the asyncio loop (`call_soon_threadsafe` / `asyncio.Queue`)
- [x] **GPIO-03**: Mock service exposes a `trigger(name)` test seam so button presses can be injected without hardware
- [ ] **GPIO-04**: GPIO settings (per-button BOARD pin numbers, debounce ms, poll interval, `poweroff_cmd`, `gpio_enabled`) exist in `Settings` with documented defaults matching the confirmed pin map (7/15/29/31)
- [x] **GPIO-05**: The service is registered in the app lifespan and its background task is cleanly cancelled on shutdown with no orphaned threads

### Button Actions

- [ ] **BTN-01**: Pressing the power button (pin 7) powers off the Jetson via the scoped `sudo /sbin/poweroff` command
- [ ] **BTN-02**: Pressing the interrupt button (pin 15) stops playing audio and clears the current playback state
- [ ] **BTN-03**: Pressing the image button (pin 29) generates an image from the currently-playing story's parameters (via `cover_prompt_builder` + the existing image generator) and shows it on the kiosk
- [ ] **BTN-04**: Pressing the image button with nothing playing is a safe no-op that fires a short error LED blink (no crash, no stale image)
- [ ] **BTN-05**: Pressing the LED-animation button (pin 31) plays a predefined LED-strip animation
- [ ] **BTN-06**: Power-off is also reachable from the admin panel via `POST /api/system/poweroff` (same scoped sudo path)
- [ ] **BTN-07**: Each button is debounce-guarded so a single press fires its handler exactly once (no repeat-fire)

### LED Animation

- [x] **ANIM-01**: `LedAnimator.rainbow(duration_ms)` plays a one-shot rainbow overlay that auto-clears after duration_ms and resumes the base mode (D-01..D-04). The engine is the sole writer to the strip — no separate animation API on the LEDService driver.
- [x] **ANIM-02**: Rainbow overlay renders distinct per-pixel hue frames during its active duration, then auto-clears to resume the base mode — safe mid-playback (D-04). The mock engine-equivalent records that the rainbow effect was invoked.

### Kiosk Events

- [ ] **KIOSK-01**: The server tracks the currently-playing story in a `PlaybackState` holder, populated when playback starts and cleared on stop
- [ ] **KIOSK-02**: `GET /api/system/events` streams interrupt and image-ready events to the kiosk via SSE (reusing the existing SSE approach)
- [ ] **KIOSK-03**: The kiosk opens an `EventSource` at startup; an interrupt event returns the UI to IDLE/home (`transitionTo(STATES.IDLE)`)
- [ ] **KIOSK-04**: An image-ready event displays the generated image in an overlay on the kiosk

### Device Setup

- [ ] **SETUP-01**: `HARDWARE_GPIO.md` documents jetson-io pinmux for pins 7/15/29/31, gpio-group permissions, the scoped `/etc/sudoers.d/storybot-poweroff` rule, and per-button wiring (pin↔GND, internal pull-up → press = LOW)
- [ ] **SETUP-02**: `Jetson.GPIO` is added as an aarch64-only optional dependency in `pyproject.toml` (mirrors `spidev`)
- [ ] **SETUP-03**: Each button is validated on wired Jetson hardware — power-off, story interrupt, on-screen image, and live LED animation all confirmed, with a clean shutdown leaving no orphaned processes

## v2 Requirements

Deferred to future release.

_None — milestone is fully scoped by `gpio_usage.md`._

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Image button "raw text" path | Image is built from the current story's parameters via `cover_prompt_builder`, not arbitrary text |
| Printing the generated image | Image button shows on the kiosk screen only; printing stays the admin sticker flow |
| Configurable button→action remapping UI | Fixed 4-button mapping; no runtime reassignment |
| GPIO output / actuators (relays, motors) | Buttons are read-only inputs this milestone |
| More than 4 buttons | Four actions confirmed; header pins reserved but unused |
| Broader sudo for the app | Power-off scoped to exactly `/sbin/poweroff` via sudoers — least privilege |

## Traceability

Which phases cover which requirements. Filled during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| GPIO-01 | Phase 35 | Complete |
| GPIO-02 | Phase 35 | Complete |
| GPIO-03 | Phase 35 | Complete |
| GPIO-04 | Phase 35 | Pending |
| GPIO-05 | Phase 35 | Complete |
| BTN-01 | Phase 36 | Pending |
| BTN-02 | Phase 36 | Pending |
| BTN-03 | Phase 36 | Pending |
| BTN-04 | Phase 36 | Pending |
| BTN-05 | Phase 36 | Pending |
| BTN-06 | Phase 36 | Pending |
| BTN-07 | Phase 36 | Pending |
| ANIM-01 | Phase 35 | Complete |
| ANIM-02 | Phase 35 | Complete |
| KIOSK-01 | Phase 36 | Pending |
| KIOSK-02 | Phase 37 | Pending |
| KIOSK-03 | Phase 37 | Pending |
| KIOSK-04 | Phase 37 | Pending |
| SETUP-01 | Phase 38 | Pending |
| SETUP-02 | Phase 35 | Pending |
| SETUP-03 | Phase 38 | Pending |
