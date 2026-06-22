# Roadmap: storybot

## Milestones

| Version | Name | Phases | Status | Completed |
|---------|------|--------|--------|-----------|
| v1.0 | MVP | 00–06 | Shipped | 2026-03-18 |
| v1.1 | Quality | 07–11 | Shipped | 2026-04-17 |
| v1.2 | AI Story Generation | 12–16 | Shipped | 2026-05-14 |
| v1.3 | Dispositivo Noia | 17–21 | Shipped | 2026-05-26 |
| v1.4 | WiFi Access | 22–25 | Code complete | - |
| v1.5 | Bluetooth Loudspeaker | 26–30 | Code complete | - |
| v1.6 | LED Strip (SPI WS2812B) | 31–34 | Code complete | - |
| v1.7 | GPIO Pushbuttons | 35–38 | In progress | - |

## Current Milestone: v1.7 GPIO Pushbuttons

**Theme:** Four physical pushbuttons on the Jetson J2 40-pin header let a teacher operate StoryBot without the touchscreen — power off, interrupt a story, generate an on-screen image from the current story, and trigger an LED animation. Source of truth: `gpio_usage.md`.

**Venue split (mirrors v1.6):** Phases 35–37 are pure x86/CI work — they land green against the `Mock` services seam (config, service logic, LED animation, SSE/kiosk, action handlers monkeypatched). Phase 38 is Jetson-only: real button presses, jetson-io pinmux, the scoped sudoers rule, and clean shutdown — the same isolation v1.6 used for Phase 34.

**Phase Numbering:**
- Integer phases (35, 36, 37): planned milestone work — continue numbering from v1.6 (Phase 34), do NOT reset.
- Decimal phases (e.g. 36.1): urgent insertions (marked INSERTED), executed in numeric order.

- [x] **Phase 35: GPIO service foundation + config + LED animation** - HardwareService Mock/Real GPIO service, factory probe, lifespan task, Settings fields, `Jetson.GPIO` optional dep, and `LedAnimator.rainbow()` one-shot overlay effect (completed 2026-06-22)
- [ ] **Phase 36: Button actions + power-off + playback state** - Four button handlers wired to existing services (power-off, interrupt, generate-image, animation), debounce-once guard, `POST /api/system/poweroff`, and the server-side PlaybackState holder
- [ ] **Phase 37: Kiosk event channel + image overlay** - `GET /api/system/events` SSE stream, kiosk EventSource, interrupt → IDLE, and image-ready overlay
- [ ] **Phase 38: On-device Jetson validation + setup docs** - `HARDWARE_GPIO.md` (pinmux, gpio group, scoped sudoers, wiring) and wired-hardware validation of all four buttons with clean shutdown

## Phase Details

### Phase 35: GPIO service foundation + config + LED animation
**Goal**: A mock-by-default GPIO button service exists behind the project's HardwareService pattern, is registered in the app lifespan, and the existing LEDService can play and cancel named animations — all green on x86/CI with no hardware.
**Depends on**: Nothing (first phase of v1.7); builds on the existing HardwareService/HardwareManager/lifespan and LEDService
**Requirements**: GPIO-01, GPIO-02, GPIO-03, GPIO-04, GPIO-05, ANIM-01, ANIM-02, SETUP-02
**Success Criteria** (what must be TRUE):
  1. `create_gpio_service()` returns the mock under `TESTING` or when `Jetson.GPIO` import / pin access fails on non-aarch64, and returns the real service only on Jetson — mirroring `create_led_service()`
  2. The mock exposes a `trigger(name)` test seam so a button press can be injected without hardware, and `Settings` carries the BOARD pin defaults (7/15/29/31), debounce ms, poll interval, `poweroff_cmd`, and `gpio_enabled`
  3. The service registers in the app lifespan and its background task is cancelled cleanly on shutdown with no orphaned threads (verified by a lifespan test over the mock)
   4. `LedAnimator.rainbow(duration_ms)` plays a one-shot rainbow hue-cycle overlay that auto-clears after the duration and resumes the base mode — modeled on the `flash()` lifecycle (D-01..D-04). No separate animation API exists; the engine is the sole writer to the strip.
  5. `Jetson.GPIO` is declared as an aarch64-only optional dependency in `pyproject.toml`, mirroring `spidev`, and the dev/CI install is unaffected
**Plans**: 4 plans
- [x] 35-01-PLAN.md — GPIO Service Infrastructure (GPIO-01, GPIO-02, GPIO-03, GPIO-05)
- [x] 35-02-PLAN.md — GPIO Settings fields + pyproject.toml dep (GPIO-04, SETUP-02)
- [x] 35-03-PLAN.md — Rainbow one-shot LED effect (ANIM-01, ANIM-02)
- [ ] 35-04-PLAN.md — Amend ROADMAP SC #4 + REQUIREMENTS.md ANIM-01/ANIM-02 per D-05 (gap closure)

### Phase 36: Button actions + power-off + playback state
**Goal**: Each of the four buttons drives its intended action through existing services exactly once per press, power-off is also reachable from the admin panel, and the server tracks the currently-playing story so the image button knows what to render.
**Depends on**: Phase 35
**Requirements**: BTN-01, BTN-02, BTN-03, BTN-04, BTN-05, BTN-06, BTN-07, KIOSK-01
**Success Criteria** (what must be TRUE):
  1. Triggering the power button invokes the scoped `sudo /sbin/poweroff` command (monkeypatched in tests via the `system_control.poweroff()` helper), and the same path is reachable via `POST /api/system/poweroff`
  2. Triggering the interrupt button calls `AudioPlayer.stop()`, clears `PlaybackState`, and enqueues an interrupt event; triggering the image button builds a prompt from the current story params via `cover_prompt_builder` + the existing image generator and enqueues an image-ready event
  3. Triggering the image button with nothing playing is a safe no-op that fires a short error LED blink (no crash, no stale image); triggering the animation button plays a predefined LED animation
  4. `PlaybackState` is populated when playback starts and cleared on stop, and each button is debounce-guarded so a single press fires its handler exactly once (no repeat-fire)
**Plans**: TBD

### Phase 37: Kiosk event channel + image overlay
**Goal**: Physical button presses reach the kiosk over SSE — an interrupt sends the UI home and an image-ready event shows the generated image — reusing the existing SSE approach and overlay markup.
**Depends on**: Phase 36
**Requirements**: KIOSK-02, KIOSK-03, KIOSK-04
**Success Criteria** (what must be TRUE):
  1. `GET /api/system/events` holds an SSE connection open and streams interrupt and image-ready events drained from the shared event queue (mock-triggered in tests)
  2. The kiosk opens an `EventSource('/api/system/events')` at startup and an interrupt event returns the UI to home via `transitionTo(STATES.IDLE)`
  3. An image-ready event displays the generated image in an overlay on the kiosk, reusing the existing overlay markup style
**Plans**: TBD
**UI hint**: yes

### Phase 38: On-device Jetson validation + setup docs
**Goal**: The four buttons work on wired Jetson hardware end-to-end, and a teacher can reproduce the device setup from documentation. Jetson-only; not verifiable from the dev machine.
**Depends on**: Phase 37
**Requirements**: SETUP-01, SETUP-03
**Success Criteria** (what must be TRUE):
  1. `HARDWARE_GPIO.md` documents jetson-io pinmux for pins 7/15/29/31, gpio-group permissions, the scoped `/etc/sudoers.d/storybot-poweroff` rule, and per-button wiring (pin↔GND, internal pull-up → press = LOW)
  2. On wired Jetson hardware, pressing the power button shuts the device down via the scoped sudo path, and pressing interrupt stops the playing story and returns the kiosk home
  3. On wired Jetson hardware, pressing the image button shows an on-screen image generated from the current story, and pressing the animation button drives a live LED-strip animation
  4. A clean shutdown leaves no orphaned processes or threads (background GPIO task cancelled cleanly)
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 35 → 36 → 37 → 38

| Phase | Milestone | Plans Complete | Status | Venue | Completed |
|-------|-----------|----------------|--------|-------|-----------|
| 35. GPIO service foundation + config + LED animation | v1.7 | 0/TBD | Not started | x86 / CI (mock) | - |
| 36. Button actions + power-off + playback state | v1.7 | 0/TBD | Not started | x86 / CI (mock) | - |
| 37. Kiosk event channel + image overlay | v1.7 | 0/TBD | Not started | x86 / CI (mock) | - |
| 38. On-device Jetson validation + setup docs | v1.7 | 0/TBD | Not started | Jetson hardware only | - |

---
*Roadmap created: 2026-06-22 — v1.7 GPIO Pushbuttons (Phases 35–38)*
