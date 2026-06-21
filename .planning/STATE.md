---
gsd_state_version: 1.0
milestone: v1.6
milestone_name: LED Strip
status: executing
stopped_at: Phase 34 Plan 34-01 RED tests committed
last_updated: "2026-06-22T09:01:00.000Z"
last_activity: 2026-06-22
progress:
  total_phases: 4
  completed_phases: 3
  total_plans: 15
  completed_plans: 9
  percent: 60
---

# Project State

## Project Reference

**Core value:** Children can hear AI-generated personalized stories and stories recorded by their teachers on demand.

**Current focus:** Phase 34 — on-device-jetson-validation-deployment

## Current Position

Phase: 34 (on-device-jetson-validation-deployment) — EXECUTING
Plan: 1 of 3 (34-01 RED tests committed, 34-02 and 34-03 pending)
Status: Plan 34-01 RED phase complete; Plan 34-02 ready for GREEN implementation
Progress: [███████░░░] 70%
Last activity: 2026-06-22

## Milestone Phases

| Phase | Name | Requirements | Venue |
|-------|------|--------------|-------|
| 31 | Driver foundation + config + capability probe | LED-01..05 (5) | x86 / CI (mock) |
| 32 | Async animation engine | LED-06..09 (4) | x86 / CI (mock) |
| 33 | LED behaviors + child-safety | LED-10..25 (16) | x86 / CI (mock) |
| 34 | On-device Jetson validation + deployment | LED-26..27 (2) | Jetson hardware only |

## Accumulated Context

**Decisions (from research / requirements lock):**

- Stack: raw `spidev` + hand-rolled ~40-line WS2812B bit-encoder. NOT `rpi_ws281x` (Pi-only PWM/DMA, absent on Tegra); NOT Blinka/NeoPixel_SPI as primary (platformdetect fails to ID Orin Nano Super).
- Two-layer split: synchronous-at-heart `RealLEDService` driver (GRB + gamma + brightness cap below the service boundary) + a NEW async `LedAnimator` single-writer render loop.
- Encoding: lock Option A (6.4 MHz / 8 SPI bits per WS bit) vs Option B (~3.8 MHz / 4-bit divisor-tolerant fallback) — freeze `led_spi_speed_hz` with matching bit pattern; confirm clock on-device in Phase 34.
- Capability probe checks the device node (`/dev/spidev{bus}.{dev}` exists AND W_OK on aarch64), not a Python import — `spidev` imports fine on x86 with no hardware.
- `POST /api/system/led` stays RGB-in / RGB-echo-out (503-when-missing preserved); routed through the animator as a solid-color request. New animation routes are additive, never overload `/led`.

**Open todos / watch-items carried into planning:**

- CRITICAL: every blocking `spidev.xfer` must be offloaded via `asyncio.to_thread` so the single event loop streaming TTS/NFC SSE is never stalled — add a latency regression test mirroring the "first audio under 2.0s" guard (Phase 32).
- Child-safety invariants (≤3 flashes/sec, brightness cap, gamma) enforced as engine/driver-level invariants, not per-effect (Phase 33).
- Remove stale `led_strip_device = "/dev/ttyUSB0"` serial default from config (Phase 31).
- Preserve story `led_color` semantics (logical sRGB; hue-preserving gamma+cap only) so shipped stories don't drift.
- Run full 320+ suite and `gitnexus_detect_changes()` before any commit; `test_create_led_service_returns_mock` will legitimately change to the new probe.

**Blockers:** None for phases 31–33 (all land green on x86/CI against the mock). Phase 34 requires the physical Jetson + wired strip — user has confirmed hardware is on hand.

**Electrical watch-items for Phase 34 (hardware acceptance, not app code):**

- 3.3V→5V level margin: 330Ω is NOT a level shifter. May need 74AHCT125, or power strip at ~4.3–4.5V, or sacrifice first LED as regenerating pixel (account for in `LED_COUNT`).
- SPI node name uncertainty: SPI1 on Orin Nano JetPack 6.2.1 commonly enumerates as `/dev/spidev0.0` — never hardcode; confirm after `jetson-io`.
- External 5V supply, 1000µF bulk cap, mandatory common ground.

## Session Continuity

**Last session:** 2026-06-22T09:01:00.000Z
**Stopped at:** Phase 34 Plan 34-01 RED tests committed
**Resume file:** None

**Next action:** Execute Plan 34-02 (install.sh SPI1-enable implementation) to turn RED tests GREEN, then proceed to Plan 34-03 (LED-27 visual UAT checklist).

**Files of interest (from research):**

- MOD `app/services/led_controller.py` — real driver + `set_pixels` on protocol/mock; rewrite `create_led_service()` probe
- NEW `app/services/led_spi.py` — pure `encode_ws2812(pixels) -> bytes` + thin `SpiWriter` (unit-testable, no hardware)
- NEW `app/services/led_animator.py` — render loop + priority state machine + frame generators
- MOD `app/config.py` — LED fields; remove stale serial default
- MOD `app/main.py` (lifespan) — construct `LedAnimator`, `create_task`, cancel/await on shutdown, boot sweep
- MOD `app/routers/system.py` — route `/led` & `/led/off` through the animator
- MOD `app/routers/nfc.py`, `app/routers/generate.py` — wire tap/param/GO/thinking/playback/end events (Phase 33)
- MOD `pyproject.toml` — `spidev` aarch64 optional dep

## Performance Metrics

| Phase | Plan | Duration | Notes |
|-------|------|----------|-------|
| Phase 32 P03 | 7m | 2 tasks | 6 files |
| Phase 33 P01 | 30 | - tasks | - files |
| Phase 34 P01 | 5m | 1 task | 2 files (test + summary) |

## Decisions

- [Phase ?]: 32-03: LedAnimator started unconditionally in lifespan (no TESTING guard, D-12); sole writer over mock in CI and real driver in prod
- [Phase ?]: 32-03: /led + /led/off route through animator.set_base/off; led_service.set_color no longer called by the route (D-11)
- [Phase ?]: Pure effect-math tests call render functions directly (no asyncio, no wall-clock)
- [Phase ?]: Engine tests drive tick_once() frame-by-frame via injected _FakeClock
- [Phase ?]: Route tests use TestClient with real lifespan (engine starts over MockLEDService)
- [Phase 34]: D-02: SPI1 enablement uses `config-by-function.py -o dt spi1` (NOT `config-by-hardware.py -n 2='spi1'`) per RESEARCH.md Pitfall 1
- [Phase 34]: D-02: udev rule uses least-privilege GROUP="spi" MODE="0660" (not 0666/plugdev)
