# Bluetooth Audio — Deploy / Dependency Notes (PLAT-07)

> **Requirement:** PLAT-07 — `pipewire-alsa` compatibility for A2DP audio
> output to a connected Bluetooth speaker.
>
> **Status:** This is a **documentation / dependency acknowledgement only**.
> **No audio-routing code ships in Phase 26.** The actual routing work
> (`pactl` / PipeWire sink selection, wired-jack fallback) lands in
> **Phase 27 (Bluetooth Pairing & Audio Routing)** and **Phase 30
> (Cleanup & Platform Validation)**, which consume this dependency.

## Why `pipewire-alsa` is required

On the two production targets — **NVIDIA Jetson Orin Nano Super** (JetPack
6.2.1, Ubuntu 22.04) and **Raspberry Pi** (64-bit Raspberry Pi OS /
Ubuntu) — the audio stack is **PipeWire** (the modern sound server that
replaces PulseAudio). StoryBot plays generated narration through
`simpleaudio`, which is an **ALSA** client. ALSA clients cannot talk to a
PipeWire sound server directly; they require the **`pipewire-alsa`
compatibility layer**, which exposes an ALSA PCM device backed by
PipeWire. Without it, `simpleaudio` either fails to open the device or
plays to a dead default sink, so the story audio never reaches the
connected Bluetooth speaker.

In short:

```
simpleaudio (ALSA client)
      │
      ▼
pipewire-alsa   ←── this compatibility layer MUST be installed
      │
      ▼
PipeWire (sound server)  ──►  Bluetooth A2DP sink (connected speaker)
```

## What Phase 26 ships (and does NOT ship)

| Item | In Phase 26? |
|------|--------------|
| Bluetooth device **discovery** (scan for name/MAC/RSSI) | Yes (Plans 02–03) |
| Paired-speaker **memory** (`content/bt_devices.json`) | Yes (Plan 01) |
| Platform **detection** (jetson / rpi / generic) | Yes (Plan 01, informational only) |
| A2DP **pairing / connecting** to a speaker | **No — Phase 27** |
| `pactl` / PipeWire **audio routing** to the speaker | **No — Phase 27 / 30** |
| `pipewire-alsa` **install / dependency note** | **Yes — this file (PLAT-07)** |

Phase 26 deliberately stops at discovery + memory + platform detection.
Connecting to a speaker and routing audio through PipeWire is a separate,
larger surface that belongs to Phase 27 and Phase 30.

## Install instruction (for Phase 27 / 30 deploy, not automated here)

This is the dependency this note acknowledges. It is **not** executed by
any Phase 26 script — it is recorded here so Phase 27 / 30 (and the
on-device hardware UAT) know what must be present on the target:

```bash
# On the Jetson Orin Nano / Raspberry Pi target (NOT the dev machine):
sudo apt update
sudo apt install -y pipewire-alsa
```

Verify the ALSA→PipeWire bridge is active:

```bash
# Should list PipeWire-backed PCM devices (not raw hw: devices only):
aplay -L | grep -E 'pipewire|alsa_output'
```

## References

- **PLAT-07** (REQUIREMENTS.md) — canonical requirement text.
- **Phase 27** — Bluetooth Pairing & Audio Routing (consumes this dep).
- **Phase 30** — Cleanup & Platform Validation (validates on-device).
- `deploy/bluetooth-audio.service` — the legacy oneshot auto-connect unit
  this milestone **replaces** in Phase 30 (PLAT-05). Do not edit it in
  Phase 26; it remains as a reference for the working `pactl`/A2DP
  incantation until Phase 30 removes it.

---

*Phase 26 — Plan 01, Task 4. Documentation only; no routing code in
Phase 26.*
