---
gsd_state_version: 1.0
milestone: v1.7
milestone_name: GPIO Pushbuttons
status: executing
stopped_at: Phase 35 context gathered
last_updated: "2026-06-22T09:54:37.566Z"
last_activity: 2026-06-22
progress:
  total_phases: 4
  completed_phases: 0
  total_plans: 3
  completed_plans: 1
  percent: 0
---

# Project State

## Project Reference

**Core value:** Children can hear AI-generated personalized stories and stories recorded by their teachers on demand.

**Current focus:** Phase 35 — gpio-service-foundation-config-led-animation

## Current Position

Phase: 35 (gpio-service-foundation-config-led-animation) — EXECUTING
Plan: 2 of 3
Status: Ready to execute
Last activity: 2026-06-22

## Milestone Phases

| Phase | Name | Requirements | Venue |
|-------|------|--------------|-------|
| 35 | GPIO service foundation + config + LED animation | GPIO-01..05, ANIM-01..02, SETUP-02 (8) | x86 / CI (mock) |
| 36 | Button actions + power-off + playback state | BTN-01..07, KIOSK-01 (8) | x86 / CI (mock) |
| 37 | Kiosk event channel + image overlay | KIOSK-02..04 (3) | x86 / CI (mock) |
| 38 | On-device Jetson validation + setup docs | SETUP-01, SETUP-03 (2) | Jetson hardware only |

## Accumulated Context

**Decisions (from `gpio_usage.md` confirmed decisions):**

- 4 buttons = 4 actions (image-gen and LED animation are separate buttons). Pin map (Jetson.GPIO BOARD mode = physical J2 pin): power=GPIO09/pin 7; interrupt=GPIO12/pin 15; image=GPIO01/pin 29; animation=GPIO11/pin 31. Buttons wired to GND, internal pull-up (press = LOW).
- GPIO service follows the existing `HardwareService` Mock/Real pattern with a `create_gpio_service()` factory mirroring `create_led_service()` — mock under `TESTING` or when `Jetson.GPIO` import / pin access fails on non-aarch64.
- Real service bridges `add_event_detect` thread callbacks to the asyncio loop via `loop.call_soon_threadsafe` / `asyncio.Queue` (push-based, mirrors `nfc_handler`); NOT 20 ms polling as the primary path.
- Image source = the parameters of the currently-playing story via the existing `cover_prompt_builder.build()` + the image-generator call path in `app/routers/generate.py` (no new "raw text" path). Image output shows on the kiosk screen (not print).
- Power-off scoped to exactly `/sbin/poweroff` via `/etc/sudoers.d/storybot-poweroff` NOPASSWD; isolated behind `system_control.poweroff()` for monkeypatch-testability; also reachable via `POST /api/system/poweroff`.
- LED "animation" = a small named-effect registry of cancellable coroutines added to the existing `LEDService` (currently only `set_color`/`turn_off`); a new animation cancels any running one; mock records the last animation name.
- Two server→client SSE channels reuse the existing SSE approach: interrupt → `transitionTo(STATES.IDLE)`; image-ready → overlay. Server-side `PlaybackState` holder tracks the current story (set when playback starts, cleared on stop).

**Open todos / watch-items carried into planning:**

- TDD red/green per CLAUDE.md for every new unit (config defaults, mock `trigger()` fires correct handler, LED animate start/stop, SSE drain, PlaybackState set/clear).
- Surgical changes only — reuse `HardwareService`/`HardwareManager`/lifespan, `cover_prompt_builder`, the `generate.py` image path, `AudioPlayer.stop()`, and the existing `transitionTo(STATES.IDLE)` + overlay markup. No refactor of the audio/image pipelines; only add `animate`/`stop_animation` to `LEDService`.
- GPIO background task must be cancelled cleanly on shutdown with no orphaned threads (lifespan test over the mock); mirror how `bt_monitor_task` is created/cancelled in `app/main.py` (~lines 198, 211–213).
- `Jetson.GPIO` added to the `jetson` aarch64-only extra in `pyproject.toml` (mirrors `spidev`); dev/CI install unaffected.
- Run the full suite + `gitnexus_detect_changes()` before any commit. Note MEMORY: real ACR122U + `.env STORYBOT_AI=1` can deadlock multiple TestClient lifespan tests (leaked pyscard thread) — NOT a code regression; judge by scoped tests.

**Blockers:** None for Phases 35–37 (all land green on x86/CI against the mock). Phase 38 requires the physical Jetson — jetson-io pinmux (pins 7/15/29/31), gpio-group permissions, the scoped sudoers rule, and wired buttons — same Jetson-only isolation v1.6 used for Phase 34.

**Jetson-only watch-items for Phase 38 (hardware acceptance, not app code):**

- On JetPack 6.2.1, `Jetson.GPIO` may use the `gpiod` backend; the `add_event_detect` callback-on-thread model still holds — confirm on-device.
- Pinmux: `sudo /opt/nvidia/jetson-io/jetson-io.py` to set pins 7/15/29/31 to GPIO, then reboot.
- Permissions: add the app user to the `gpio` group (or the udev rule Jetson.GPIO ships).
- Sudoers: `/etc/sudoers.d/storybot-poweroff` → `storybot ALL=(root) NOPASSWD: /sbin/poweroff` (only that exact command).
- Validate clean shutdown leaves no orphaned processes/threads.

## Session Continuity

**Last session:** 2026-06-22T09:54:37.534Z
**Stopped at:** Phase 35 context gathered
**Resume file:** None

**Next action:** Plan Phase 35 (`/gsd-plan-phase 35`) — GPIO service foundation + config + LED animation.

**Files of interest (from `gpio_usage.md`):**

- NEW `app/services/gpio_handler.py` — `GPIOButtonService` Mock/Real + `create_gpio_service()` factory + handler methods (`_on_power`/`_on_interrupt`/`_on_image`/`_on_animation`)
- NEW `app/services/system_control.py` — `poweroff()` helper (monkeypatchable)
- NEW `tests/test_services/test_gpio_handler.py`, `tests/test_services/test_gpio_config.py`
- NEW `HARDWARE_GPIO.md` (NOT in `.planning`) — pinmux, gpio group, scoped sudoers, wiring (Phase 38)
- MOD `app/services/led_controller.py` — add `animate`/`stop_animation` + named-effect registry (Phase 35)
- MOD `app/config.py` — GPIO `Settings` fields (Phase 35)
- MOD `pyproject.toml` — `Jetson.GPIO` aarch64 optional dep (Phase 35)
- MOD `app/routers/system.py` — `GET /api/system/events` SSE + `POST /api/system/poweroff` (Phases 36–37)
- MOD `app/main.py` (lifespan) — register GPIO service, shared event queue + `PlaybackState` on `app.state`, cancel task on shutdown (Phases 35–36)
- MOD `static/children/script.js` — `EventSource('/api/system/events')`, interrupt → IDLE, image overlay, report current story (Phase 37)

## Performance Metrics

| Phase | Plan | Duration | Notes |
|-------|------|----------|-------|
| — | — | — | v1.7 not yet executed |
| Phase 35 P01 | 15 minutes | 3 tasks | 4 files |

## Decisions

- [Roadmap v1.7]: Phases continue from v1.6 (Phase 34) — start at Phase 35, no reset.
- [Roadmap v1.7]: Venue split mirrors v1.6 — Phases 35–37 x86/CI (mock seam); Phase 38 Jetson-only (SETUP-01 docs + SETUP-03 hardware validation).
- [Roadmap v1.7]: ANIM-01/02 placed in Phase 35 (foundation) because BTN-04 (error blink) and BTN-05 (animation button) consume `animate()`.
- [Roadmap v1.7]: KIOSK-01 (PlaybackState) placed in Phase 36 because the image-button handler (BTN-03) reads the current story from it.
- [Roadmap v1.7]: SETUP-02 (`Jetson.GPIO` optional dep) placed in Phase 35 (config-time, lands green on x86); SETUP-01/03 deferred to Jetson Phase 38.
- [Phase ?]: Follow Mock/Real/factory pattern from led_controller.py for GPIO service
- [Phase ?]: _real_gpio_available() is monkeypatchable probe
- [Phase ?]: Factory never raises: returns mock when probe fails
