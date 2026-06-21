# Roadmap: storybot

## Milestones

| Version | Name | Phases | Status | Completed |
|---------|------|--------|--------|-----------|
| v1.0 | MVP | 00-06 | Shipped | 2026-03-18 |
| v1.1 | Quality | 07-11 | Shipped | 2026-04-17 |
| v1.2 | AI Story Generation | 12-16 | Shipped | 2026-05-14 |
| v1.3 | Dispositivo Noia | 17-21 | Shipped | 2026-05-26 |
| v1.4 | WiFi Access | 22-25 | Code complete (on-device UAT pending) | ~2026-06-01 |
| v1.5 | Bluetooth Loudspeaker Connection | 26-30 | Code complete (Phase 30 + on-device UAT pending) | — |
| v1.6 | LED Strip (SPI WS2812B) | 31-34 | In progress | — |

> **Reconciliation note (2026-06-12):** v1.3 Noia and v1.4 WiFi history was merged in from the other development machine (it matches the committed code). The Bluetooth milestone started on 2026-06-12 was re-slotted from "v1.3" to **v1.5** to avoid colliding with the existing v1.3/v1.4. Its phases were already numbered 26-30, which follow naturally after WiFi's phase 25. v1.4 WiFi is left in-progress/paused; v1.5 Bluetooth is the active focus.

> **v1.6 note (2026-06-20):** v1.5 Bluetooth treated as code-complete (phases 26-29 implemented; phase 30 cleanup + on-device UAT outstanding) to start v1.6 LED Strip. v1.6 phases **continue numbering from v1.5**, starting at **Phase 31**.

## Current Milestone: v1.6 LED Strip (SPI WS2812B) (Phases 31-34)

**Theme:** Replace the placeholder `RealLEDService` with a working WS2812B-over-SPI driver on the Jetson (SPI1_MOSI / J12 pin 19, ~8–30 LEDs) plus a single-writer async animation engine driving playback pulse, tap/feedback flashes, idle/thinking, and boot/status — keeping the existing real/mock capability-probe factory so x86 dev and CI stay green against the mock.

**Verification split:** Phases 31–33 land fully green in CI against the mock (the whole point of the existing real/mock architecture). Phase 34 isolates all irreducible on-device tuning (pinmux, electrical bring-up, timing/visual UAT) into the single hardware phase — matching how the project already defers NFC/BT/WiFi hardware validation. User has confirmed the physical Jetson and wired strip are on hand.

**Key constraints honored:** vanilla-JS frontend only; existing real/mock Protocol hardware-service + capability-probe factory pattern; must NOT break the existing mock LED tests or the `POST /api/system/led` RGB-in / RGB-echo-out contract (gamma/cap/GRB conversion lives below the service boundary); TDD red/green is the default; 8GB shared-RAM Jetson (per-frame sleep, no busy-spin).

### v1.6 Phases

- [x] **Phase 31: Driver foundation + config + capability probe** - Real WS2812B SPI driver (GRB/gamma/brightness-cap/reset encoder), framebuffer rewrite, `/dev/spidev` writability probe, aarch64-only `spidev` dep, config fields
- [x] **Phase 32: Async animation engine** - Single-writer asyncio render loop in lifespan, `asyncio.to_thread` SPI offload, priority state machine with transient-flash restore, `POST /api/system/led` routed through the engine, latency regression test (completed 2026-06-21)
- [ ] **Phase 33: LED behaviors + child-safety** - The four LED moments (playback pulse, pause hold, fade-to-idle, tap/GO/error flashes, idle glow, thinking, boot sweep) + differentiators (param accumulation, generation progress bar, health beacon, cross-fades), wired into nfc.py/generate.py using story `led_color`; ≤3 flashes/sec + brightness cap + gamma as engine invariants
- [ ] **Phase 34: On-device Jetson validation + deployment** - jetson-io SPI1 enablement + spidev udev/group permissions automated in install flow, electrical bring-up, tune `led_spi_speed_hz`, visual UAT of every behavior on the wired strip

### v1.6 Phase Details

#### Phase 31: Driver foundation + config + capability probe

**Goal**: The placeholder `RealLEDService` becomes a working WS2812B SPI driver that correctly encodes an N-pixel framebuffer, while the real/mock factory keeps x86 dev and CI green on the mock.
**Depends on**: Phase 30 (first phase of v1.6; builds on existing v1.0–v1.5 codebase — no functional dependency on the outstanding Phase 30 cleanup)
**Requirements**: LED-01, LED-02, LED-03, LED-04, LED-05
**Success Criteria** (what must be TRUE):

  1. A commanded RGB color is encoded to the correct WS2812B SPI byte stream — GRB order, gamma-corrected, brightness-capped, with a ≥50µs trailing reset latch (asserted by golden-vector encoder unit tests)
  2. `create_led_service()` returns the real driver only when running on aarch64 with `/dev/spidev{bus}.{dev}` present AND writable (W_OK), and the mock otherwise — so the dev machine and CI run unchanged on the mock
  3. LED count, brightness cap, SPI bus/device, clock speed, color order, and gamma are all read from `config.py` (no hardcoded device node; the stale `led_strip_device = "/dev/ttyUSB0"` serial default is removed)
  4. Importing the app on x86 never requires `spidev`; the dependency installs only on aarch64 as an optional dependency
  5. The existing `test_led.py` suite still passes (the `create_led_service` mock-selection assertion is deliberately updated to the new probe; the `MockLEDService` public surface is unchanged)

**Plans**: 3 plans (2 waves)

**Wave 1** *(parallel, no file overlap)*

- [x] 31-01-PLAN.md — (TDD) Pure WS2812B SPI byte-encoder `encode_ws2812()` + thin `SpiWriter` in new `app/services/led_spi.py`; golden-vector encoder tests in new `tests/test_services/test_led_spi.py` lock GRB order, gamma LUT, cap-before-gamma, ≥50µs reset latch, total length, determinism (LED-01, LED-02 + LED-05 module-import-safety half) (wave 1)
- [x] 31-02-PLAN.md — Config + manifest: add 7 LED `Settings` fields (`led_count`, `led_max_brightness`, `led_spi_bus`, `led_spi_dev`, `led_spi_speed_hz`, `led_color_order`, `led_gamma`); remove stale `led_strip_device="/dev/ttyUSB0"` (D-06); add `spidev>=3.6` aarch64-only marker under `jetson` extra (D-05); new `tests/test_services/test_led_config.py` (LED-03, LED-05 manifest half) (wave 1)

**Wave 2** *(blocked on Wave 1; depends on 31-01 encoder + 31-02 config fields)*

- [x] 31-03-PLAN.md — Rewrite `create_led_service()` as never-raise aarch64+W_OK+TESTING-precedence factory (D-03, D-12); rewrite `RealLEDService` as N-pixel framebuffer driving `encode_ws2812` via `SpiWriter` (RGB-in contract preserved, D-04); expand `tests/test_services/test_led.py::TestCreateLEDService` with 8 monkeypatched probe cases cloned from `test_bt_manager.py::TestFactory` (LED-04, LED-01 integration half, LED-05 regression half); MockLEDService + LEDService Protocol unchanged (D-07) (wave 2, depends 31-01, 31-02)

#### Phase 32: Async animation engine

**Goal**: A single long-lived async render loop becomes the sole writer to the strip, preempts cleanly between states, and never blocks the event loop that streams TTS audio and NFC events.
**Depends on**: Phase 31
**Requirements**: LED-06, LED-07, LED-08, LED-09
**Success Criteria** (what must be TRUE):

  1. One background animation loop starts at app startup (mirroring the existing `bt_monitor` lifespan task) and is cleanly cancelled/awaited on shutdown — it is the only code path that writes to the strip
  2. With an animation actively running, an SSE event (NFC tap / TTS `audio_ready`) is still delivered within budget — a latency regression test (mirroring the "first audio under 2.0s" guard) confirms SPI writes are offloaded off the event loop via `asyncio.to_thread`
  3. Issuing a new LED request preempts the current animation on the next tick; a transient flash plays over the current persistent state and restores it when finished
  4. `POST /api/system/led` still accepts RGB and echoes RGB back (503-when-missing preserved), now setting a solid color through the animation engine rather than poking hardware directly

**Plans**: 3 plans (3 waves)

**Wave 0** *(test scaffold — Nyquist)*

- [x] 32-01-PLAN.md — Wave 0 failing-test scaffold: `test_led_animator.py` (LED-06/LED-08 preempt-restore + dirty-check via `tick_once()` + injected clock), `test_led_latency.py` (LED-07 responsiveness mirror), extend `test_system.py` (LED-09 route→engine + 503 stubs); existing 8 `/led` tests stay green (LED-06, LED-07, LED-08, LED-09) (wave 0)

**Wave 1** *(blocked on Wave 0)*

- [x] 32-02-PLAN.md — (TDD) `LedAnimator` render engine in new `app/services/led_animator.py`: drift-free ~30 FPS loop (D-05), two-slot base+overlay preempt/restore latest-wins (D-07/D-08/D-10), dirty-check before write (D-06), `asyncio.to_thread` SPI offload (D-01), injectable `now` clock; driver/mock surface unchanged (LED-06, LED-08) (wave 1, depends 32-01)

**Wave 2** *(blocked on Wave 1)*

- [x] 32-03-PLAN.md — Lifespan wiring (construct + `create_task` + cancel/gather, UNCONDITIONAL start over the mock per D-12), `get_led_animator` dependency, reroute `/led` + `/led/off` through the engine (D-11), green the LED-07 latency + LED-09 route/503 tests (LED-06, LED-07, LED-09) (wave 2, depends 32-01, 32-02)

#### Phase 33: LED behaviors + child-safety

**Goal**: The strip becomes a non-verbal status language for pre-readers — breathing playback, calm confirmations, ambient idle/thinking, boot self-test — with child-safety limits enforced below the effect API.
**Depends on**: Phase 32
**Requirements**: LED-10, LED-11, LED-12, LED-13, LED-14, LED-15, LED-16, LED-17, LED-18, LED-19, LED-20, LED-21, LED-22, LED-23, LED-24, LED-25
**Success Criteria** (what must be TRUE):

  1. While a story plays, the strip breathes in the story's `led_color`; it holds steady-dim while paused, resumes breathing on resume, and fades back to idle when the story ends
  2. The strip gives a brief confirmation flash on NFC tap, lights one additional pixel per parameter card tapped, confirm-flashes on GO commit, and advances a per-pixel progress indicator as each generated story segment streams (`audio_ready`)
  3. The strip shows a calm ambient idle glow at rest, an animated "thinking" effect during AI generation, a gentle amber error indication on failure (never a red strobe), and an idle-only low amber health beacon when a hardware service is down (never interrupting a playing story)
  4. On boot the strip runs a startup self-test sweep that lights every pixel to confirm the SPI path, then settles to idle; transitions between states use smooth gamma-corrected cross-fades rather than hard cuts
  5. No effect ever flashes faster than 3 times/sec and all output is clamped to the configured maximum brightness — enforced as engine-level invariants regardless of what an effect requests (verified by safety-clamp unit tests)

**Plans**: 6 plans (4 waves)

**Wave 0** *(test scaffold — Nyquist)*

- [x] 33-01-PLAN.md — Failing-test scaffold: `test_led_effects.py` (LED-10/15/17/18/19/20 pure-math RED), extend `test_led_animator.py` (LED-11/12/13/14/15/16/18/21/22/23 mode/rate-limit/cross-fade/beacon RED), `test_api/test_led_state.py` (D-02 route RED) + extend `test_led_latency.py` (animated-effect latency); existing engine/latency tests stay green (LED-10..LED-25) (wave 0)

**Wave 1** *(blocked on Wave 0)*

- [ ] 33-02-PLAN.md — (TDD) Pure `app/services/led_effects.py` render fns (breathe/comet/progress/param_fill/boot_wipe/idle_glow/error_amber) + effect tunable config fields; RGB-above-boundary, no gamma/cap inside effects (CF-1/CF-2); greens `test_led_effects.py` (LED-10, LED-15, LED-16, LED-17, LED-18, LED-19, LED-20, LED-22, LED-24, LED-25) (wave 1, depends 33-01)

**Wave 2** *(blocked on Wave 1; load-bearing engine refactor)*

- [ ] 33-03-PLAN.md — (TDD) `LedAnimator` mode/priority layer (D-13) + per-pixel `_render_base`/framebuffer `tick_once`, ≤3-flash/sec rate-limit gate (D-19/LED-23), gamma-correct RGB cross-fades (D-17/LED-22), error override+auto-fade+clear-on-action (D-15/D-16), engine-internal boot sweep (D-10/LED-18), idle-only health beacon (D-14/LED-21); engine plumbing untouched; greens `test_led_animator.py` (LED-10, LED-11, LED-12, LED-13, LED-14, LED-15, LED-16, LED-17, LED-18, LED-21, LED-22, LED-23, LED-24) (wave 2, depends 33-01, 33-02)

**Wave 3** *(blocked on Wave 2; parallel, no file overlap)*

- [ ] 33-04-PLAN.md — Additive `POST /api/system/led/state` (D-02, enum 422 default-deny, backend `led_color` resolution D-03) + remove client-side LED animation from `script.js` (D-04, one semantic signal per transition); greens `test_led_state.py` (LED-10, LED-11, LED-12, LED-22) (wave 3, depends 33-01, 33-03)
- [ ] 33-05-PLAN.md — Wire backend-observed triggers (D-01): NFC tap flash (LED-13), param accumulation (LED-19), GO flash (LED-14) in `nfc.py`; thinking comet (LED-17), per-`audio_ready` progress running-known-N (LED-20), generation-error amber (LED-15) in `generate.py`; all through the engine, None-guarded (LED-13, LED-14, LED-15, LED-17, LED-19, LED-20) (wave 3, depends 33-03)
- [ ] 33-06-PLAN.md — Lifespan health-beacon status feed into the engine via `set_health` from `HardwareManager` (D-05/D-14) + boot-sweep startup confirmation (LED-18); Phase 32 CR-01 shutdown ordering preserved; lifespan test (LED-18, LED-21) (wave 3, depends 33-03)

**UI hint**: no

#### Phase 34: On-device Jetson validation + deployment

**Goal**: SPI1 is enabled and permissioned through the install flow, the strip is electrically brought up on the physical Jetson, and every LED behavior is validated visually on real hardware.
**Depends on**: Phase 33
**Requirements**: LED-26, LED-27
**Success Criteria** (what must be TRUE):

  1. SPI1 enablement (jetson-io / pinmux) and spidev permissions (udev rule + group membership) are documented and automated in the install flow so the service user can open `/dev/spidev*` without manual steps
  2. The `bus.dev` → `/dev/spidevX.Y` node mapping for pin 19 is confirmed on the device, `led_spi_speed_hz` is tuned so the encoded WS2812B timing renders cleanly (correct first pixel, no flicker), and config defaults are locked
  3. Every LED behavior from Phase 33 (playback breathing, pause hold, fade, tap/GO/error flashes, idle glow, thinking, boot sweep, progress indicators, health beacon) is visually validated on the wired strip for color fidelity, timing, and brightness — including a story-color spot-check

**Plans**: TBD

## Code Complete: v1.5 Bluetooth Loudspeaker Connection (Phases 26-30)

**Theme:** Replace hardcoded BT connect script with managed Bluetooth audio service. Teachers pair speakers from admin panel, system auto-reconnects on boot, audio falls back to wired jack when speaker disconnects.

**Platforms:** Jetson Orin Nano (JetPack 6.2.1) + Raspberry Pi 4/5 (Pi OS)

**Status (2026-06-20):** Treated as code-complete to start v1.6. Phases 26–29 implemented; Phase 30 (old-script removal + README + RPi validation) and on-device UAT remain outstanding.

### v1.5 Phases

- [x] **Phase 26: BT Service Foundation** — D-Bus client, device scanning, paired device memory, Real/Mock pattern (completed 2026-06-15)
- [x] **Phase 27: Pairing + Audio Routing** — BlueZ Agent1, pair/forget, A2DP connect pipeline, wired fallback (completed 2026-06-18)
- [x] **Phase 28: Boot Reconnect + Resilience** — Auto-reconnect on boot, health monitoring, mid-story disconnect recovery (completed 2026-06-19)
- [x] **Phase 29: Admin BT UI** — Collapsible BT section, scan/one-tap pair+connect/forget/disconnect controls, real-time status display, set-output-to-max on connect (volume slider descoped per D-02) (completed 2026-06-19)
- [ ] **Phase 30: Platform Validation + Cleanup** — Replace old scripts, update README, validate on Jetson and RPi

### v1.5 Phase Details

#### Phase 26: BT Service Foundation

**Goal**: The system can discover nearby Bluetooth audio devices and remembers previously paired speakers across restarts
**Depends on**: Phase 25 (first phase of v1.5; builds on existing v1.0–v1.4 codebase)
**Requirements**: PLAT-01, PLAT-03, PLAT-07, BT-01, BT-06, BT-07, TEST-BT-01
**Success Criteria** (what must be TRUE):

  1. Backend discovers nearby Bluetooth audio devices and returns their name, MAC address, and signal strength
  2. Backend persists a list of previously paired speakers (name + MAC) that survives app restarts
  3. MockBtManager provides simulated scan/device data for testing without BT hardware
  4. Platform detection correctly identifies Jetson, RPi, and dev machine environments**Plans**: 3 plans (3 waves)

**Wave 1**

- [x] 26-01-PLAN.md — Foundation: BtDevice/BtStatus/LastSpeaker models, BtDeviceStore persistence, detect_platform(), dbus-fast dep + gitignore (wave 1)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 26-02-PLAN.md — BtManager service: base/Real/Mock + never-raises factory, dbus-fast scan, audio filter + RSSI sort (wave 2)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 26-03-PLAN.md — /api/bt/* router + main.py wiring + platform on /api/system/status (wave 3)

#### Phase 27: Pairing + Audio Routing

**Goal**: Teachers can pair and connect Bluetooth speakers, and audio routes correctly to the connected speaker or falls back to the wired jack
**Depends on**: Phase 26
**Requirements**: BT-02, BT-03, BT-04, BT-05, AUDIO-01, AUDIO-02, AUDIO-06, PLAT-02, PLAT-04, TEST-BT-02, TEST-BT-03
**Success Criteria** (what must be TRUE):

  1. A teacher can pair a new Bluetooth speaker from a headless device without physical interaction (NoInputNoOutput agent)
  2. Audio plays through the connected Bluetooth speaker when one is connected (A2DP profile active)
  3. Audio automatically falls back to the 3.5mm wired jack when no BT speaker is connected
  4. A teacher can disconnect or forget a previously paired speaker
  5. All BT API endpoints (scan, pair, connect, disconnect, status) have passing integration tests

**Plans**: TBD

#### Phase 28: Boot Reconnect + Resilience

**Goal**: The system automatically reconnects to the last-used speaker on boot and recovers from mid-story Bluetooth disconnections without teacher intervention
**Depends on**: Phase 27
**Requirements**: BOOT-01, BOOT-02, BOOT-03, BOOT-04, AUDIO-05, TEST-BT-04
**Success Criteria** (what must be TRUE):

  1. On Jetson boot, the system automatically reconnects to the last-used Bluetooth speaker
  2. On Raspberry Pi boot, the system automatically reconnects to the last-used Bluetooth speaker
  3. When a BT speaker disconnects mid-story, audio seamlessly switches to the wired jack without interrupting playback
  4. Boot reconnection retries with exponential backoff for up to 5 minutes before giving up
  5. A periodic health check detects silent/failed BT connections and triggers fallback to wired output

> **Scope correction (planning, 2026-06-18):** AUDIO-05 is planned as **sink-switch-only**. Research confirmed story audio is browser-owned (Chromium `<audio>` → default PipeWire sink), not server-side simpleaudio. CONTEXT decisions D-08 (restart current segment), D-09 (immediate-reconnect signaling), and D-10 (route back at segment boundary) are **superseded**: on a mid-story drop the monitor switches the default sink to wired and PipeWire stream-follow moves the live browser stream — no segment restart, no client↔server segment signaling. Stream-follow seamlessness (assumption A1) is a Phase 30 hardware Manual-Only check.

**Plans**: 5 plans (3 waves)

**Wave 0** *(test scaffold — Nyquist)*

- [x] 28-00-PLAN.md — Shared hardware-free test fixtures in tests/conftest.py (fake clock, await-able fake sleep, pre-seeded MockBtManager, stub route) (wave 0)

**Wave 1** *(blocked on Wave 0; parallel, no file overlap)*

- [x] 28-01-PLAN.md — Boot-reconnect module app/bt_boot_reconnect.py (TDD): bounded exponential backoff (≤5 min), run-once-then-exit, give-up→wired, python -m entrypoint; TEST-BT-04 mock scenarios (BOOT-01/02/03, TEST-BT-04) (wave 1)
- [x] 28-02-PLAN.md — Health monitor app/services/bt_monitor.py (TDD): D-06 OR health probe, AUDIO-05 sink-switch fallback (D-08/09/10 superseded), D-07 idle self-heal, D-13 steady-state retry, exception-safe loop, D-14 status state (BOOT-04, AUDIO-05) (wave 1)

**Wave 2** *(blocked on Wave 1; parallel, no file overlap)*

- [x] 28-03-PLAN.md — Status surface + lifespan wiring: BtStatus health_state/device_name (D-14), /api/bt/status overlay, BtMonitor started/cancelled in lifespan app.state (BOOT-04, AUDIO-05) (wave 2, depends 28-02)
- [x] 28-04-PLAN.md — Deployment: shared oneshot systemd unit deploy/storybot-bt-boot.service + install.sh template/enable/linger/disable-old (BOOT-01, BOOT-02) (wave 2, depends 28-01)

#### Phase 29: Admin BT UI

**Goal**: Teachers can manage Bluetooth speakers entirely from the admin panel without SSH or command-line access
**Depends on**: Phase 28
**Requirements**: UIBT-01, UIBT-02, UIBT-03, UIBT-04, AUDIO-03 (UIBT-05 and AUDIO-04 descoped per D-01/D-02)
**Success Criteria** (what must be TRUE):

  1. Admin panel has a collapsible "Bluetooth" section with scan, pair, forget, connect, and disconnect controls
  2. Admin panel shows real-time BT connection status (connected/disconnected/scanning) with device name
  3. Admin panel displays signal strength as visual bars for discovered devices
  4. Admin panel shows the current audio output device (BT speaker name or "Wired")
  5. ~~Teacher can adjust speaker volume from a slider in the admin panel~~ **DESCOPED (D-01/D-02):** no volume slider; on connect the output sink is driven to 100% and the speaker's physical volume control is authoritative

**Plans**: 3/3 plans complete

**Wave 1** *(parallel, no file overlap)*

- [x] 29-01-PLAN.md — (TDD) Backend: route_to_bt sets output sink to 100% on connect (D-01); AUDIO-03 context; UIBT-05/AUDIO-04 documented descoped (wave 1)
- [x] 29-02-PLAN.md — Admin BT section markup + header icon + signal-bar/state-transition/accordion CSS (UIBT-01, UIBT-03, UIBT-04, AUDIO-03) (wave 1)

**Wave 2** *(blocked on 29-02)*

- [x] 29-03-PLAN.md — Admin BT controller (script.js): scan, one-tap pair+connect, forget, disconnect, expanded-only status poll, header icon, accordion (UIBT-01, UIBT-02, UIBT-03, UIBT-04, AUDIO-03) (wave 2, depends 29-02)

**UI hint**: yes

#### Phase 30: Platform Validation + Cleanup

**Goal**: Deploying StoryBot with Bluetooth no longer requires manual script setup; documentation reflects the new managed workflow
**Depends on**: Phase 29
**Requirements**: PLAT-05, PLAT-06
**Success Criteria** (what must be TRUE):

  1. The old `scripts/bluetooth-connect.sh` and `deploy/bluetooth-audio.service` are removed and replaced by the managed BT service
  2. README.md documents the managed Bluetooth setup workflow without manual instructions

**Plans**: TBD

## Code Complete: v1.4 WiFi Access

**Theme:** Connect StoryBot to the school's WiFi network so teachers can push app updates remotely without physical access to the device.

**Status:** All four phases implemented and tested in code (156 WiFi/update tests passing as of 2026-06-12). The `/tmp` planning snapshot (2026-05-28) was stale — the actual implementation landed 2026-06-01 (commits 282f8c9, e5d4a13, b5d685d, 68abeea), with deploy refinements through 2026-06-12 (avahi/DNS, autostart, non-Jetson install, routing). **Remaining:** on-device/mobile UAT (24-02, 25-02 human-verification steps) and WiFi-hardware validation on the Jetson — not verifiable from the dev machine.

### v1.4 Phases

- [x] **Phase 22: WiFi Backend + Deploy Config** — WifiManager + nmcli, polkit, never-default (completed 2026-06-01)
- [x] **Phase 23: OTA Update Backend** — Git-based update check, apply with rollback, service restart via API (completed 2026-06-01)
- [x] **Phase 24: Admin WiFi UI** — WiFi section: scan, connect modal, header status indicator (code complete 2026-06-01; mobile UAT pending)
- [x] **Phase 25: Admin Updates UI** — Update badge, install button, SSE progress modal, footer version (code complete 2026-06-01; mobile UAT pending)

### v1.4 Phase Details

#### Phase 22: WiFi Backend + Deploy Config

**Goal**: Device can scan, connect to, and disconnect from WiFi networks via API, with credentials persisting across reboots
**Depends on**: Phase 21
**Requirements**: WIFI-04, WIFI-05, INFRA-09
**Success Criteria** (what must be TRUE):

  1. `GET /api/wifi/scan` returns a list of nearby WiFi networks with SSID and signal strength
  2. `POST /api/wifi/connect` with SSID and password connects the Jetson to a WPA2-PSK network (verified by `GET /api/wifi/status` returning connected state)
  3. `POST /api/wifi/disconnect` disconnects the device from the current WiFi network
  4. After connecting to a WiFi network, rebooting the device, and checking status again, the WiFi connection is automatically re-established without teacher intervention
  5. All nmcli operations work without password prompts (polkit rule deployed)

#### Phase 23: OTA Update Backend

**Goal**: Device can check for, apply, and safely roll back StoryBot app updates via API
**Depends on**: Phase 22
**Requirements**: OTA-01, OTA-04, OTA-05, INFRA-10
**Success Criteria** (what must be TRUE):

  1. `GET /api/updates/check` compares local HEAD against remote and returns whether an update is available
  2. `POST /api/updates/apply` fetches the latest code, runs `uv sync`, performs a health check, and restarts the service — observable via SSE progress stream
  3. If the health check fails after pulling new code, the service automatically rolls back to the previous working commit and remains operational
  4. `GET /api/updates/version` returns the current app version (git describe or commit hash)
  5. The storybot service can restart itself without sudo password prompts (sudoers drop-in deployed)

#### Phase 24: Admin WiFi UI

**Goal**: Teachers can manage the device's WiFi connection entirely from the admin panel on their phone
**Depends on**: Phase 22
**Requirements**: WIFI-01, WIFI-02, WIFI-03
**Success Criteria** (what must be TRUE):

  1. Teacher sees a list of available WiFi networks with signal strength indicators in the admin panel
  2. Teacher can tap a network, enter a WPA2-PSK password, and see the device connect with success/failure feedback
  3. Admin panel header shows the current WiFi connection status (connected network name or "not connected")
  4. Teacher can disconnect from the current network via a button in the admin panel

#### Phase 25: Admin Updates UI

**Goal**: Teachers can see when an update is available and install it from the admin panel
**Depends on**: Phase 23, Phase 24
**Requirements**: OTA-02, OTA-03
**Success Criteria** (what must be TRUE):

  1. When an update is available, a notification badge appears in the admin panel (without teacher action)
  2. Teacher can tap "Install update" and see real-time progress (fetching, syncing, restarting) via SSE stream
  3. After update completes and service restarts, the admin panel auto-reconnects and shows the new version number

## Completed Milestones

<details>
<summary>v1.3 Dispositivo Noia (Phases 17-21) — SHIPPED 2026-05-26</summary>

**Theme:** Make StoryBot run on any Linux device — auto-detect AI capability at startup, gracefully hide AI features on weaker hardware.

- [x] Phase 17: Backend Capability Probe (4/4 plans) — completed 2026-05-19
- [x] Phase 18: API Surface & Router Guards (3/3 plans) — completed 2026-05-20
- [x] Phase 19: Kiosk Frontend Gating (2/2 plans) — completed 2026-05-21
- [x] Phase 20: Admin Frontend Gating (2/2 plans) — completed 2026-05-25
- [x] Phase 21: Deployment Adaptation (2/2 plans) — completed 2026-05-25

**Archive:** `.planning/milestones/v1.3-ROADMAP.md`

</details>

<details>
<summary>v1.2 AI Story Generation (Phases 12-16) — SHIPPED 2026-05-14</summary>

**Theme:** Children compose stories by tapping parameter NFC cards, hear them streamed in real-time with generated cover art, teachers curate the growing library.

- [x] Phase 12: Parameter card system (2/2 plans) — completed 2026-04-21
- [x] Phase 13: LLM story generation — Qwen 3.5 4B + llama.cpp (2/2 plans) — completed 2026-04-22
- [x] Phase 14: Streaming TTS pipeline (2/2 plans) — completed 2026-04-22
- [x] Phase 15: Cover image generation (2/2 plans) — completed 2026-05-05
- [x] Phase 16: Kiosk UX + library + Jetson verification (6/6 plans) — completed 2026-05-13

**Archive:** `.planning/milestones/v1.2-ROADMAP.md`

</details>

<details>
<summary>v1.1 Quality (Phases 07-11) — SHIPPED 2026-04-17</summary>

- [x] Phase 07: Fix Pause/Resume Audio (1/1 plan) — completed 2026-03-19
- [x] Phase 08: Foundation Verification (1/1 plan) — completed 2026-03-24
- [x] Phase 08.1: Fix Piper TTS Dependency (1/1 plan) — completed 2026-03-24
- [x] Phase 09: Documentation Cleanup (1/1 plan) — completed 2026-03-24
- [x] Phase 10: Test Coverage — Foundation & Story Playback (1/1 plan) — completed 2026-03-24
- [x] Phase 11: Test Coverage — UI Features (1/1 plan) — completed 2026-04-17

</details>

<details>
<summary>v1.0 MVP (Phases 00-06) — SHIPPED 2026-03-18</summary>

- [x] Phase 00: Foundation (3 plans)
- [x] Phase 01: Story Playback (5 plans)
- [x] Phase 02: UI/UX Improvements (5 plans)
- [x] Phase 03: Emoji Picker UX (1 plan)
- [x] Phase 04: Story Edit (2 plans)
- [x] Phase 05: Pause/Resume Audio (1 plan)
- [x] Phase 05.1: Jetson Deployment Script (1 plan)
- [x] Phase 06: Complete Foundation Infrastructure (1 plan)

</details>

## Progress

**Execution order (active):** 31 -> 32 -> 33 -> 34 (v1.6). v1.5 Bluetooth is code-complete (Phase 30 cleanup + on-device UAT outstanding); v1.4 is code-complete (on-device/mobile UAT only).

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 22. WiFi Backend + Deploy Config | v1.4 | 3/3 | Complete | 2026-05-27 |
| 23. OTA Update Backend | v1.4 | 3/3 | Complete | 2026-05-27 |
| 24. Admin WiFi UI | v1.4 | 2/2 | Code complete (UAT pending) | 2026-06-01 |
| 25. Admin Updates UI | v1.4 | 2/2 | Code complete (UAT pending) | 2026-06-01 |
| 26. BT Service Foundation | v1.5 | 3/3 | Complete | 2026-06-15 |
| 27. Pairing + Audio Routing | v1.5 | 8/8 | Complete | 2026-06-18 |
| 28. Boot Reconnect + Resilience | v1.5 | 5/5 | Complete | 2026-06-19 |
| 29. Admin BT UI | v1.5 | 3/3 | Complete | 2026-06-19 |
| 30. Platform Validation + Cleanup | v1.5 | 0/? | Not started | - |
| 31. Driver foundation + config + capability probe | v1.6 | 3/3 | Complete | 2026-06-20 |
| 32. Async animation engine | v1.6 | 3/3 | Complete    | 2026-06-21 |
| 33. LED behaviors + child-safety | v1.6 | 1/6 | In Progress|  |
| 34. On-device Jetson validation + deployment | v1.6 | 0/? | Not started | - |

---
*Roadmap created: 2026-03-19*
*Last updated: 2026-06-20 — Added v1.6 LED Strip (SPI WS2812B) milestone, phases 31-34 (LED-01..LED-27, 100% mapped). v1.5 Bluetooth re-headed as code-complete.*
