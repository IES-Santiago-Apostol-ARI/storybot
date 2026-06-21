# Requirements: StoryBot

**Defined:** 2025-03-06
**Core Value:** A child taps their NFC card and immediately hears their story with colorful LED feedback

## v1 Requirements

Requirements for MVP release (Phases 0-1: Setup + Narrated Stories).

### Infrastructure

- [x] **INFRA-01**: FastAPI server runs on port 8000 with proper project structure
- [x] **INFRA-02**: Piper TTS installed with Spanish voice (es_ES-sharvard-medium)
- [x] **INFRA-03**: NFC reader (ACR122U) detected and reads card UIDs
- [x] **INFRA-04**: LED strip controllable via USB (color change on command)
- [x] **INFRA-05**: Audio playback service plays MP3/WAV files through speakers
- [x] **INFRA-06**: WiFi hotspot configured (TP-Link AP at 192.168.0.1)
- [x] **INFRA-07**: Systemd service starts FastAPI + Chromium kiosk on boot

### Stories

- [x] **STORY-01**: Teacher can create a new story with title, audio file, emoji, and LED color
- [x] **STORY-02**: Teacher can list all stories in the library
- [x] **STORY-03**: Teacher can delete a story from the library
- [x] **STORY-04**: Stories stored as JSON metadata + audio files on filesystem
- [x] **STORY-05**: Story audio supports teacher-recorded narration (MP3 upload)

### NFC Integration

- [x] **NFC-01**: NFC handler runs in dedicated thread (non-blocking)
- [x] **NFC-02**: Card tap triggers SSE event with card UID
- [x] **NFC-03**: Teacher can associate NFC card UID with a story
- [x] **NFC-04**: Card tap on children's interface triggers story playback

### Admin Panel

- [x] **ADMIN-01**: Admin panel accessible at /admin via mobile browser
- [x] **ADMIN-02**: Admin panel accessible without authentication (local network security)
- [x] **ADMIN-03**: Upload form accepts audio file + story metadata
- [x] **ADMIN-04**: Story list shows all stories with delete option
- [x] **ADMIN-05**: NFC write button associates current card with selected story

### Children's Interface

- [x] **CHILD-01**: Kiosk interface at / runs in fullscreen Chromium
- [x] **CHILD-02**: No text — icons and images only for navigation
- [x] **CHILD-03**: Large touch targets (minimum 100x100px)
- [x] **CHILD-04**: Story selection via icon grid or NFC tap
- [x] **CHILD-05**: Playback screen shows story cover + animated feedback
- [x] **CHILD-06**: No escape gestures — locked kiosk mode

### Feedback

- [x] **FEED-01**: LED changes to story's assigned color on playback start
- [x] **FEED-02**: LED animation during story (slow pulse or solid)
- [x] **FEED-03**: Screen shows visual feedback during playback (cover + animation)
- [x] **FEED-04**: End screen with "thank you" animation when story finishes

## v1.1 Requirements

Requirements for UI/UX polish (Phase 2).

### Shared Theme

- [x] **UI-THEME-01**: Shared CSS design tokens (colors, radii, shadows, animations) across both interfaces

### Children's Kiosk UI

- [x] **UI-KIOSK-01**: Scattered card layout with varied rotations and sizes (bookshelf feel)
- [x] **UI-KIOSK-02**: Empty state shows animated sleeping character when no stories exist
- [x] **UI-KIOSK-03**: Touch glow feedback on story cards
- [x] **UI-KIOSK-04**: 3D page-turn transition between screens
- [x] **UI-KIOSK-05**: Animated progress character moves across bottom during playback
- [x] **UI-KIOSK-06**: Bouncy entrance animations for story cards
- [x] **UI-KIOSK-07**: Subtle UI sounds (tap on selection, chime on completion)

### Admin Panel UI

- [x] **UI-ADMIN-01**: Hardware status icons in header (NFC, LED)
- [x] **UI-ADMIN-02**: Status icons update via polling to show connection state

## v1.2 Requirements

Requirements for admin panel enhancements (Phases 3-4).

### Story Editing

- [x] **EDIT-01**: PUT endpoint accepts optional file uploads (keeps existing if not provided)
- [x] **EDIT-02**: Edit button on story cards opens pre-filled form with story data
- [x] **EDIT-03**: Edit mode UI shows Cancel button and allows discarding changes

## v1.3 Requirements

Requirements for playback controls (Phase 5).

### Pause/Resume

- [x] **PAUSE-01**: Tap on playback screen toggles audio pause/resume
- [x] **PAUSE-02**: Visual pause indicator (icon overlay) and animation freeze when paused
- [x] **PAUSE-03**: LED holds at medium brightness when paused, smoothly resumes pulse on play

## v1.4 Requirements — Milestone v1.3 Dispositivo Noia

**Capability detection and graceful AI degradation.**

### Capability Detection

- [x] **CAP-01**: App probes GPU presence and available RAM at FastAPI lifespan startup
- [x] **CAP-02**: Env var `STORYBOT_AI` provides override: unset = auto-detect, `0` = force disable, `1` = force enable
- [x] **CAP-03**: Capability state stored in `app.state.ai_enabled` and accessible to all routers
- [x] **CAP-04**: When AI is disabled, AI services (StoryGenerator, SwapOrchestrator, TTSPipeline) are not initialized

### API Surface

- [x] **API-01**: `GET /api/capabilities` returns `{ai_enabled, tts_available, cover_gen, printer, reason}`
- [x] **API-02**: `POST /api/generate/story` returns 503 with `{"error": "AI not available on this device"}` when AI disabled
- [x] **API-03**: All other endpoints (`/api/stories`, `/api/nfc/*`, `/api/printer/*`, `/api/system/*`) work identically regardless of AI capability

### Kiosk Frontend

- [x] **KSK-01**: Kiosk JS fetches `/api/capabilities` on DOMContentLoaded, stores in global variable
- [x] **KSK-02**: NFC handler skips `card_type="parameter"` and `card_type="go"` events when `ai_enabled=false`, plays tap sound only
- [x] **KSK-03**: Thinking overlay and parameter chip display never shown on non-AI device
- [x] **KSK-04**: Curated story playback works identically with or without AI capability

### Admin Frontend

- [x] **ADM-06**: Admin JS fetches `/api/capabilities` on DOMContentLoaded
- [x] **ADM-07**: Admin hides parameter card registration section (`.cards-section`) when AI disabled
- [x] **ADM-08**: Admin hides generated stories section (`.generated-section`) when AI disabled
- [x] **ADM-09**: Admin hides "Registrar Parametro" and "Registrar Go" buttons when AI disabled
- [x] **ADM-10**: Admin shows capability badge in header: "Modo: Completo" (AI on) or "Modo: Basico (sin IA)" (AI off)

### Deployment

- [x] **DEP-01**: install.sh detects device type and writes appropriate `STORYBOT_AI` env var to .env
- [x] **DEP-02**: systemd llama-server.service is conditional — skipped on non-AI devices
- [x] **DEP-03**: Same codebase and same install script works on Jetson (full AI) and generic Linux (stories only)

## v1.5 Requirements — Milestone v1.4 WiFi Access

**WiFi connectivity and OTA app updates.**

### WiFi Management

- [x] **WIFI-01**: Teacher can view a list of available WiFi networks from the admin panel
- [x] **WIFI-02**: Teacher can connect the device to a WPA2-PSK WiFi network by entering the password
- [x] **WIFI-03**: Teacher can see the current WiFi connection status in the admin panel
- [x] **WIFI-04**: WiFi connection persists across device reboots without reconfiguration
- [x] **WIFI-05**: Teacher can disconnect the device from the current WiFi network

### OTA Updates

- [x] **OTA-01**: Device automatically checks for available StoryBot app updates
- [x] **OTA-02**: Teacher sees a notification in the admin panel when an update is available
- [x] **OTA-03**: Teacher can trigger app update installation from the admin panel
- [x] **OTA-04**: Failed updates automatically roll back to the previous working version
- [x] **OTA-05**: Teacher can see the current app version in the admin panel

### Infrastructure

- [x] **INFRA-09**: Install script configures polkit rule for passwordless WiFi management
- [x] **INFRA-10**: Install script extends sudoers drop-in for storybot service restart

## v1.6 Requirements — Milestone v1.5 Bluetooth Loudspeaker Connection

Managed Bluetooth audio service (scan/pair/connect/route) for Jetson Orin Nano and Raspberry Pi 4/5. Phases 26-30.

### Bluetooth Device Management

- [ ] **BT-01**: System can scan for nearby Bluetooth audio devices and return name, MAC address, and signal strength
- [x] **BT-02**: Teacher can pair a Bluetooth speaker via admin panel (headless, NoInputNoOutput agent)
- [x] **BT-03**: Teacher can forget (unpair) a previously paired Bluetooth speaker via admin panel
- [x] **BT-04**: System can connect to a known (paired) Bluetooth speaker on demand
- [x] **BT-05**: System can disconnect from the current Bluetooth speaker on demand
- [ ] **BT-06**: System remembers the last N paired speakers with names and MAC addresses
- [ ] **BT-07**: Admin panel displays signal strength for discovered and connected speakers

### Audio Routing

- [x] **AUDIO-01**: Audio plays through connected Bluetooth speaker when one is connected (A2DP profile)
- [x] **AUDIO-02**: Audio falls back to wired output (3.5mm jack) when no BT speaker is connected
- [x] **AUDIO-03**: Admin panel shows current audio output device (BT speaker name or "Wired")
- [ ] ~~**AUDIO-04**: Teacher can adjust volume from admin panel; system remembers volume per speaker~~ — **DESCOPED** (Phase 29 D-01/D-02 — no per-speaker memory; output driven to 100% on connect)
- [x] **AUDIO-05**: System detects BT speaker disconnection mid-story and automatically switches to wired output without interrupting playback
- [x] **AUDIO-06**: A2DP audio profile is explicitly activated after each BT connection (Jetson JetPack compatibility)

### Boot & Reconnection

- [x] **BOOT-01**: Systemd service auto-connects to last-used BT speaker on boot (Jetson Orin Nano)
- [x] **BOOT-02**: Systemd service auto-connects to last-used BT speaker on boot (Raspberry Pi 4/5)
- [x] **BOOT-03**: Boot reconnection retries with exponential backoff for up to 5 minutes
- [x] **BOOT-04**: Periodic health check detects silent/failed BT connection and triggers fallback to wired

### Admin UI

- [x] **UIBT-01**: Admin panel has a collapsible "Bluetooth" section with scan, pair, forget, connect, disconnect controls
- [x] **UIBT-02**: Admin panel shows real-time BT connection status (connected/disconnected/scanning) with device name
- [x] **UIBT-03**: Admin panel displays signal strength as visual bars for discovered devices
- [x] **UIBT-04**: Admin panel shows animated transitions for connection state changes
- [ ] ~~**UIBT-05**: Admin panel includes volume slider that adjusts BT speaker volume~~ — **DESCOPED** (Phase 29 D-01/D-02 — no slider; output driven to 100% on connect)

### Platform & Deployment

- [ ] **PLAT-01**: BT service uses dbus-fast for BlueZ D-Bus communication (platform-agnostic)
- [x] **PLAT-02**: Audio routing uses pactl subprocess (works under both PulseAudio and PipeWire)
- [ ] **PLAT-03**: BtManager follows existing HardwareService Real/Mock protocol pattern
- [x] **PLAT-04**: Jetson JetPack A2DP blocker (nv-bluetooth-service.conf) is handled in deploy script
- [ ] **PLAT-05**: Existing `scripts/bluetooth-connect.sh` and `deploy/bluetooth-audio.service` are replaced
- [ ] **PLAT-06**: README.md updated to reflect managed BT setup (removes manual instructions)
- [ ] **PLAT-07**: pipewire-alsa compatibility layer ensured for simpleaudio audio routing on both platforms

### Testing

- [ ] **TEST-BT-01**: MockBtManager allows full API testing without BT hardware
- [ ] **TEST-BT-02**: All BT API endpoints have integration tests (scan, pair, connect, disconnect, status)
- [x] **TEST-BT-03**: Audio routing fallback behavior tested (BT disconnect → wired switch)
- [x] **TEST-BT-04**: Boot reconnection script tested (mock adapter scenarios)

## Milestone v1.6 LED Strip (SPI WS2812B) Requirements — Phases 31-34

Real WS2812B addressable LED driver over Jetson SPI1_MOSI (J12 pin 19, ~8–30 LEDs on a front status bar) replacing the placeholder `RealLEDService`, plus an async animation engine for playback, feedback, idle/thinking, and boot/status — keeping the real/mock factory so the x86 dev machine and CI stay green on the mock. See `.planning/research/SUMMARY.md`.

### LED Driver & SPI Foundation

- [x] **LED-01**: WS2812B strip displays a commanded RGB color on real hardware via Jetson SPI1_MOSI (placeholder `RealLEDService` becomes a working driver)
- [x] **LED-02**: Driver encodes an N-pixel framebuffer to WS2812B SPI bytes — GRB order, gamma-corrected, brightness-capped, with a ≥50µs reset latch
- [x] **LED-03**: LED count, brightness cap, SPI bus/device, clock speed, color order, and gamma are configurable in `config.py` (no hardcoded device node; stale serial default removed)
- [ ] **LED-04**: Service factory selects the real driver only when `/dev/spidev*` is present and writable, otherwise the mock — dev machine and CI run unchanged on the mock
- [x] **LED-05**: `spidev` installs only on aarch64 (Jetson) as an optional dependency; importing the app on x86 never requires it

### Animation Engine

- [x] **LED-06**: A single background animation loop is the sole writer to the strip, started at app startup and cleanly stopped on shutdown
- [x] **LED-07**: SPI writes never block the async event loop — audio and NFC SSE streams stay responsive while an animation runs
- [x] **LED-08**: A new LED event preempts the current animation immediately; transient flashes restore the prior persistent state when finished
- [x] **LED-09**: `POST /api/system/led` still sets a solid color (RGB-in / RGB-echo-out contract preserved), now routed through the animation engine

### LED Behaviors — Table Stakes

- [x] **LED-10**: LED breathes in the story's color while a story plays
- [x] **LED-11**: LED holds steady-dim while playback is paused and resumes breathing on resume
- [x] **LED-12**: LED fades back to idle when a story ends
- [x] **LED-13**: LED gives a brief confirmation flash on NFC card tap
- [x] **LED-14**: LED gives a confirmation flash when the child commits parameters with the GO card
- [x] **LED-15**: LED shows a gentle amber error indication on failure (never a red strobe)
- [x] **LED-16**: LED shows a calm ambient idle glow when nothing is happening
- [x] **LED-17**: LED plays an animated "thinking" effect during AI story generation
- [x] **LED-18**: LED runs a startup self-test sweep on boot that lights every pixel to confirm the SPI path

### LED Behaviors — Differentiators

- [x] **LED-19**: LED lights one additional pixel per parameter card tapped, showing accumulation toward GO
- [x] **LED-20**: LED advances a per-pixel progress indicator as each generated story segment streams (`audio_ready`)
- [x] **LED-21**: LED shows a low amber health beacon (idle only) when a hardware service is down, without interrupting a playing story
- [x] **LED-22**: Transitions between LED states use smooth cross-fades / comet polish rather than hard cuts

### Child-Safety Invariants

- [x] **LED-23**: No LED effect ever flashes faster than 3 times per second (enforced below the effect API)
- [x] **LED-24**: All LED output is clamped to a configured maximum brightness suitable for ages 3–6
- [x] **LED-25**: Brightness fades are gamma-corrected for smooth, band-free dimming

### On-Device Validation & Deployment

- [ ] **LED-26**: SPI1 enablement (jetson-io/pinmux) and spidev permissions (udev rule + group) are documented and automated in the install flow
- [ ] **LED-27**: Every LED behavior is validated on the physical Jetson with the wired strip (color fidelity, timing, brightness)

## v2 Requirements

Deferred to future milestones.

### Interactive Stories

- **INTER-01**: Branching story trees with choice points
- **INTER-02**: Touch-based choice selection (2 options)
- **INTER-03**: LED color changes based on scene emotion
- **INTER-04**: JSON schema for decision tree stories

### Capability Diagnostics

- **DIAG-01**: Admin diagnostic tooltip explaining why AI is disabled (no CUDA, insufficient RAM)
- **DIAG-02**: Per-feature capability granularity (LLM available, SD available, TTS available as separate flags)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Child accounts/profiles | NFC cards provide per-child identity |
| Video content | Storage/bandwidth, inappropriate for screen time limits |
| Gamification (points, badges) | Pedagogically inappropriate for age group |
| Usage analytics | Privacy concern |
| Mobile app | Web UI sufficient, avoids app store complexity |
| Dynamic runtime capability switching | Enormous complexity. Restart is acceptable. |
| Per-feature AI granularity | Three AI services are tightly coupled. Single boolean is sufficient. |
| Separate "light" frontend build | Same HTML/JS with conditional visibility. Two builds doubles maintenance. |
| OS/system updates via admin | Risk of bricking Jetson — CUDA/driver compat. SSH-only. |
| WiFi captive portal support | Headless device cannot handle browser-based auth. WPA2-PSK only. |
| WPA2-Enterprise WiFi | Requires certificate management. Document as known limitation. |
| Automatic update install | Interrupts active sessions, teacher loses control. Notify-only + manual trigger. |
| WiFi config from kiosk | Children ages 3-6 cannot configure WiFi. Admin-only. |
| VPN / remote SSH | Massive security surface, school policies may block it. Separate milestone if needed. |
| rpi_ws281x for LED (v1.6) | Pi-only PWM/DMA peripheral; does not exist on Tegra. WS2812B driven via raw spidev bit-encoder instead. |
| Blinka/NeoPixel_SPI as primary LED path (v1.6) | adafruit-platformdetect fails to ID Orin Nano Super; raw spidev sidesteps it. Documented fallback only. |
| Audio-reactive / strobe LED effects (v1.6) | Child-safety: ≤3 flashes/sec, no saturated red, no party mode for ages 3–6. |
| Per-child LED color identity (v1.6) | One light = one meaning at a time; status language, not personalization. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 | Phase 0 | Complete |
| INFRA-02 | Phase 0 | Complete |
| INFRA-03 | Phase 0 | Complete |
| INFRA-04 | Phase 0 | Complete |
| INFRA-05 | Phase 0 | Complete |
| INFRA-06 | Phase 6 | Complete |
| INFRA-07 | Phase 6 | Complete |
| STORY-01 | Phase 1 | Complete |
| STORY-02 | Phase 1 | Complete |
| STORY-03 | Phase 1 | Complete |
| STORY-04 | Phase 1 | Complete |
| STORY-05 | Phase 1 | Complete |
| NFC-01 | Phase 1 | Complete |
| NFC-02 | Phase 1 | Complete |
| NFC-03 | Phase 1 | Complete |
| NFC-04 | Phase 1 | Complete |
| ADMIN-01 | Phase 1 | Complete |
| ADMIN-02 | Phase 1 | Complete |
| ADMIN-03 | Phase 1 | Complete |
| ADMIN-04 | Phase 1 | Complete |
| ADMIN-05 | Phase 1 | Complete |
| CHILD-01 | Phase 1 | Complete |
| CHILD-02 | Phase 1 | Complete |
| CHILD-03 | Phase 1 | Complete |
| CHILD-04 | Phase 1 | Complete |
| CHILD-05 | Phase 1 | Complete |
| CHILD-06 | Phase 1 | Complete |
| FEED-01 | Phase 1 | Complete |
| FEED-02 | Phase 1 | Complete |
| FEED-03 | Phase 1 | Complete |
| FEED-04 | Phase 1 | Complete |
| UI-THEME-01 | Phase 2 | Complete |
| UI-KIOSK-01 | Phase 2 | Complete |
| UI-KIOSK-02 | Phase 2 | Complete |
| UI-KIOSK-03 | Phase 2 | Complete |
| UI-KIOSK-04 | Phase 2 | Complete |
| UI-KIOSK-05 | Phase 2 | Complete |
| UI-KIOSK-06 | Phase 2 | Complete |
| UI-KIOSK-07 | Phase 2 | Complete |
| UI-ADMIN-01 | Phase 2 | Complete |
| UI-ADMIN-02 | Phase 2 | Complete |
| EDIT-01 | Phase 4 | Complete |
| EDIT-02 | Phase 4 | Complete |
| EDIT-03 | Phase 4 | Complete |
| PAUSE-01 | Phase 5 | Complete |
| PAUSE-02 | Phase 5 | Complete |
| PAUSE-03 | Phase 5 | Complete |

**Coverage:**

- v1 requirements: 30 complete, 0 pending
- v1.1 requirements: 10 complete
- v1.2 requirements: 3 complete (Phase 12)
- v1.3 requirements: 3 complete
- v1.4 requirements: 19 total, 19 complete
- v1.5 requirements (WiFi Access): 12 total, 12 mapped, 12 complete (code + tests; on-device UAT pending)
- v1.6 requirements (Bluetooth, Milestone v1.5): 33 total, 33 mapped, 0 complete
- v1.6 LED Strip (Milestone v1.6, Phases 31-34): 27 total (LED-01..LED-27), 27 mapped, 0 complete
- Total complete: 77/137
- Mapped to phases: 137
- Unmapped: 0

## Traceability -- v1.6 LED Strip (SPI WS2812B) (Phases 31-34)

| Requirement | Phase | Status |
|-------------|-------|--------|
| LED-01 (commanded RGB on real WS2812B via SPI1_MOSI) | Phase 31 | Pending |
| LED-02 (N-pixel framebuffer encode: GRB/gamma/cap/reset latch) | Phase 31 | Pending |
| LED-03 (config-driven count/cap/bus/dev/speed/order/gamma; stale serial default removed) | Phase 31 | Pending |
| LED-04 (factory selects real iff /dev/spidev present + writable, else mock) | Phase 31 | Pending |
| LED-05 (spidev aarch64-only optional dep; x86 import never requires it) | Phase 31 | Pending |
| LED-06 (single background loop = sole writer; start at startup, stop on shutdown) | Phase 32 | Complete |
| LED-07 (SPI writes never block the event loop; SSE stays responsive) | Phase 32 | Complete |
| LED-08 (new event preempts immediately; transient flash restores prior state) | Phase 32 | Complete |
| LED-09 (POST /api/system/led RGB-in/RGB-echo-out preserved, routed through engine) | Phase 32 | Complete |
| LED-10 (breathe in story color during playback) | Phase 33 | Pending |
| LED-11 (steady-dim on pause, resume breathing on resume) | Phase 33 | Pending |
| LED-12 (fade back to idle when story ends) | Phase 33 | Pending |
| LED-13 (confirmation flash on NFC tap) | Phase 33 | Pending |
| LED-14 (confirmation flash on GO commit) | Phase 33 | Pending |
| LED-15 (gentle amber error indication, never red strobe) | Phase 33 | Pending |
| LED-16 (calm ambient idle glow at rest) | Phase 33 | Pending |
| LED-17 (animated "thinking" effect during AI generation) | Phase 33 | Pending |
| LED-18 (boot self-test sweep lighting every pixel) | Phase 33 | Pending |
| LED-19 (one pixel per parameter card tapped, accumulation toward GO) | Phase 33 | Pending |
| LED-20 (per-pixel generation progress advancing on audio_ready) | Phase 33 | Pending |
| LED-21 (idle-only low amber health beacon when a service is down) | Phase 33 | Pending |
| LED-22 (smooth cross-fades / comet polish between states) | Phase 33 | Pending |
| LED-23 (≤3 flashes/sec enforced below the effect API) | Phase 33 | Pending |
| LED-24 (output clamped to configured max brightness for ages 3–6) | Phase 33 | Pending |
| LED-25 (gamma-corrected, band-free brightness fades) | Phase 33 | Pending |
| LED-26 (SPI1 enablement + spidev udev/group permissions automated in install flow) | Phase 34 | Pending |
| LED-27 (every behavior validated on physical Jetson with wired strip) | Phase 34 | Pending |

## Traceability -- v1.5 Bluetooth Loudspeaker Connection (Phases 26-30)

| Requirement | Phase | Status |
|-------------|-------|--------|
| BT-01 (scan returns name/MAC/RSSI) | Phase 26 | Pending |
| BT-06 (remember last paired speaker) | Phase 26 | Pending |
| BT-07 (signal strength display) | Phase 26 / 29 | Pending |
| PLAT-01 (dbus-fast for BlueZ D-Bus) | Phase 26 | Pending |
| PLAT-03 (Real/Mock HardwareService pattern) | Phase 26 | Pending |
| PLAT-07 (pipewire-alsa compat for simpleaudio) | Phase 26 | Pending |
| TEST-BT-01 (MockBtManager hardware-free testing) | Phase 26 | Pending |
| BT-02 (pair via NoInputNoOutput agent) | Phase 27 | Pending |
| BT-03 (forget/unpair speaker) | Phase 27 | Pending |
| BT-04 (connect to known speaker) | Phase 27 | Pending |
| BT-05 (disconnect speaker) | Phase 27 | Pending |
| AUDIO-01 (audio via A2DP when connected) | Phase 27 | Pending |
| AUDIO-02 (wired fallback when no BT) | Phase 27 | Pending |
| AUDIO-06 (explicit A2DP activation) | Phase 27 | Pending |
| PLAT-02 (pactl subprocess routing) | Phase 27 | Pending |
| PLAT-04 (Jetson A2DP blocker handled) | Phase 27 | Pending |
| TEST-BT-02 (BT API integration tests) | Phase 27 | Pending |
| TEST-BT-03 (routing fallback tested) | Phase 27 | Pending |
| BOOT-01 (auto-reconnect on boot — Jetson) | Phase 28 | Pending |
| BOOT-02 (auto-reconnect on boot — RPi) | Phase 28 | Pending |
| BOOT-03 (reconnect backoff up to 5 min) | Phase 28 | Pending |
| BOOT-04 (health check → wired fallback) | Phase 28 | Pending |
| AUDIO-05 (mid-story disconnect recovery) | Phase 28 | Pending |
| TEST-BT-04 (boot reconnection tested) | Phase 28 | Pending |
| UIBT-01 (collapsible BT admin section) | Phase 29 | Pending |
| UIBT-02 (real-time BT status) | Phase 29 | Pending |
| UIBT-03 (signal strength bars) | Phase 29 | Pending |
| UIBT-04 (animated state transitions) | Phase 29 | Pending |
| UIBT-05 (volume slider) | Phase 29 | Descoped (D-01/D-02 — no slider; output driven to 100% on connect) |
| AUDIO-03 (current output device display) | Phase 29 | Pending |
| AUDIO-04 (per-speaker volume memory) | Phase 29 | Descoped (D-01/D-02 — no per-speaker memory; always max on connect) |
| PLAT-05 (replace old BT script/service) | Phase 30 | Pending |
| PLAT-06 (README managed BT setup) | Phase 30 | Pending |

## Traceability -- v1.5 WiFi Access (Phases 22-25)

| Requirement | Phase | Status |
|-------------|-------|--------|
| WIFI-01 (view available WiFi networks from admin) | Phase 24 | Complete |
| WIFI-02 (connect to WPA2-PSK network from admin) | Phase 24 | Complete |
| WIFI-03 (WiFi connection status in admin) | Phase 24 | Complete |
| WIFI-04 (WiFi persistence across reboots) | Phase 22 | Complete |
| WIFI-05 (disconnect from WiFi network) | Phase 22 | Complete |
| OTA-01 (auto-check for app updates) | Phase 23 | Complete |
| OTA-02 (update notification in admin panel) | Phase 25 | Complete |
| OTA-03 (teacher triggers update install from admin) | Phase 25 | Complete |
| OTA-04 (failed updates roll back automatically) | Phase 23 | Complete |
| OTA-05 (current app version in admin) | Phase 23 | Complete |
| INFRA-09 (polkit rule for passwordless WiFi) | Phase 22 | Complete |
| INFRA-10 (sudoers drop-in for service restart) | Phase 23 | Complete |

## Traceability -- v1.4 Dispositivo Noia (Phases 17-21)

| Requirement | Phase | Status |
|-------------|-------|--------|
| CAP-01 (startup GPU + RAM probe) | Phase 17 | Complete |
| CAP-02 (STORYBOT_AI env var override) | Phase 17 | Complete |
| CAP-03 (capability state in app.state.ai_enabled) | Phase 17 | Complete |
| CAP-04 (skip AI services when disabled) | Phase 17 | Complete |
| API-01 (GET /api/capabilities endpoint) | Phase 18 | Complete |
| API-02 (503 on POST /api/generate/story when AI disabled) | Phase 18 | Complete |
| API-03 (other endpoints unchanged regardless of AI) | Phase 18 | Complete |
| KSK-01 (kiosk fetches capabilities on load) | Phase 19 | Complete |
| KSK-02 (NFC skips parameter/GO cards when AI disabled) | Phase 19 | Complete |
| KSK-03 (thinking overlay never shown on non-AI) | Phase 19 | Complete |
| KSK-04 (curated playback works identically with/without AI) | Phase 19 | Complete |
| ADM-06 (admin fetches capabilities on load) | Phase 20 | Complete |
| ADM-07 (hide parameter cards section when AI disabled) | Phase 20 | Complete |
| ADM-08 (hide generated stories section when AI disabled) | Phase 20 | Complete |
| ADM-09 (hide Registrar Parametro/Go buttons when AI disabled) | Phase 20 | Complete |
| ADM-10 (capability badge: Completo vs Basico) | Phase 20 | Complete |
| DEP-01 (install.sh auto-detect and write STORYBOT_AI) | Phase 21 | Complete |
| DEP-02 (systemd llama-server conditional) | Phase 21 | Complete |
| DEP-03 (same codebase works on Jetson + generic Linux) | Phase 21 | Complete |

## Traceability -- Phases 07-15

| Requirement | Phase | Status |
|-------------|-------|--------|
| PAUSE-01 (retap pause/resume) | Phase 07 | Complete |
| PAUSE-02 (visual + LED feedback) | Phase 07 | Complete |
| PAUSE-03 (NFC retap debounce fix) | Phase 07 | Complete |
| INFRA-08 (piper-tts in pyproject.toml, aarch64 install) | Phase 08.1 | Complete |
| DOC-01 (REQUIREMENTS.md accuracy audit) | Phase 09 | Complete |
| TEST-01 (pytest coverage Phases 00-01) | Phase 10 | Complete |
| TEST-02 (pytest coverage Phases 02-05) | Phase 11 | Complete |
| CARD-01 (card type model + migration) | Phase 12 | Complete |
| CARD-02 (parameter card CRUD API) | Phase 12 | Complete |
| CARD-03 (NFC tap routing enriched SSE) | Phase 12 | Complete |
| CARD-04 (session buffer with timeout) | Phase 12 | Complete |
| ADMIN-06 (card registration UI) | Phase 12 | Complete |
| LLM-01 (Qwen 3.5 4B install + benchmark on Jetson) | Phase 13 | Complete |
| LLM-02 (generation API + SSE streaming) | Phase 13 | Complete |
| TTS-01 (SentenceBuffer + TTSPipeline backend) | Phase 14 | Complete |
| TTS-02 (kiosk audio queue + sequential playback) | Phase 14 | Complete |
| COVER-01 (SD pipeline install + benchmark) | Phase 15 | Complete |
| COVER-02 (cover prompt builder + swap orchestrator) | Phase 15 | Complete |

---
*Requirements defined: 2025-03-06*
*Last updated: 2026-06-20 -- added v1.6 LED Strip (SPI WS2812B) requirements LED-01..LED-27, mapped to Phases 31-34 (100% coverage, no orphans).*
