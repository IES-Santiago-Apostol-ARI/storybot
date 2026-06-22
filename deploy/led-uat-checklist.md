# LED Visual UAT Checklist (LED-27)

## Environment

| Field | Value |
|-------|-------|
| Jetson model | Orin Nano Super 8GB |
| JetPack version | 6.2.1 |
| Confirmed `/dev/spidevX.Y` node | _fill after bring-up_ |
| Final tuned `led_spi_speed_hz` | _fill after tuning (D-04)_ |
| Encoder variant (Option A / Option B) | _fill after tuning_ |
| Level shifter required? | _fill during electrical bring-up_ |

---

## Behavior Validation

Run each row by triggering the behavior via the listed API call or action, then compare the strip's actual output against the expected result. Record **Pass** or **Fail** (and notes) in the last two columns.

| # | Behavior (req) | How to trigger (exact API call / action) | Expected (color / timing / brightness) | Pass/Fail | Notes |
|---|----------------|------------------------------------------|----------------------------------------|-----------|-------|
| 1 | Boot self-test sweep (LED-18) | Restart `storybot.service` or reboot the Jetson | Single smooth single-color wipe across all 21 px in ~1.0 s (`led_boot_wipe_s`), then settles to idle glow. Not rainbow. | | |
| 2 | Idle glow (LED-16) | Leave device idle (no active mode) | Warm dim static amber glow (`led_idle_color #1A0F00`), no motion, low brightness (~30%). | | |
| 3 | Health beacon (LED-21) | Idle + force a hardware service down (e.g. unplug printer USB) | Low-amber beacon overlaid on idle ONLY; disappears when a higher-priority mode is active. | | |
| 4 | NFC tap flash (LED-13) | Tap any NFC card on the reader | One brief (~150–250 ms) neutral/white confirm flash, then return to prior state. | | |
| 5 | Parameter accumulation (LED-19) | Tap parameter cards in sequence | Each tap lights the next pixel from pixel 0 in `led_accum_color #FFFFFF` (steady). | | |
| 6 | GO commit flash (LED-14) | Tap the GO card | Distinct, slightly longer celebratory flash (e.g. green) — visibly different from the tap flash. | | |
| 7 | Thinking comet (LED-17) | Start AI generation (POST /api/generate/story) | Comet/chase: lit pixel + short tail (`led_comet_tail=3`) travels the strip in ~2.0 s loop; clearly different from breathing. | | |
| 8 | Generation progress (LED-20) | During generation, per `audio_ready` events | Pixels fill proportionally across 21 px in the story `led_color` (falls back to accum color pre-persist); bar ends full at completion. | | |
| 9 | Playback breathing (LED-10) | Play a curated story | Slow calm sinusoidal breath in the story's `led_color` (~4.5 s period, `led_breathe_period_s`); dips to ~35% (`led_breathe_trough`), never fully off. | | |
| 10 | Pause hold (LED-11) | Tap screen or NFC card during playback to pause | Breathing freezes to steady dim hold in the story's color. | | |
| 11 | Resume (LED-11) | Tap screen or NFC card again to resume | Breathing restarts from where it left off. | | |
| 12 | Fade to idle (LED-12) | Let story end naturally | Smooth ~1–2 s fade-out from breathing back to idle glow (`led_idle_color #1A0F00`). | | |
| 13 | Error indication (LED-15) | Trigger a generation error (e.g. invalid prompt) | Gentle amber (`led_error_color #FF6A00`) slow fade in/out a few cycles (< 3 flashes/s), then auto-settle; never red, never strobe. | | |
| 14 | Cross-fades (LED-22) | Transition between modes (idle ↔ thinking ↔ playback ↔ error) via rapid mode changes | All base-mode changes cross-fade smoothly (`led_crossfade_s 0.5`), no hard cuts. | | |
| 15 | ≤3 flashes/sec safety (LED-23) | Rapidly tap cards / trigger fast flashes in succession | Flashes coalesce/throttle to ≥333 ms apart — never a fast strobe. | | |
| 16 | Brightness cap (LED-24) | `curl -s -X POST http://localhost:8000/api/system/led -H 'Content-Type: application/json' -d '{"color":"#FFFFFF"}'` | Output visibly capped at ~30% (`led_max_brightness 0.30`); comfortable for ages 3–6, not blinding. | | |
| 17 | **Story-color spot-check** | Play 2–3 shipped stories with distinct `led_color` values | Rendered hue matches the logical sRGB `led_color` after gamma+cap — a dimmed red stays red, not orange (hue-preserving). | | |

---

## Post-Validation Notes

After completing all rows, record the final environment values at the top of this file. If any row failed, document the failure here and re-tune or fix before shipping.
