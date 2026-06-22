---
phase: 34
plan: 03
subsystem: led-hardware
tags: [jetson, spi, deployment, uat]
dependency-graph:
  requires: []
  provides: [led-uat-checklist, spidev-smoke-test, spi-speed-tuning-guiance]
  affects: []
tech-stack:
  added: []
  patterns: [manual-uat-checklist, shell-smoke-test]
key-files:
  created:
    - deploy/led-uat-checklist.md
  modified:
    - scripts/verify_hardware.sh
    - app/config.py
decisions: []
metrics:
  duration: ~5m
  completed-date: "2026-06-22"
---

# Phase 34 Plan 03: On-Device Jetson Validation & Deployment Summary

**One-liner:** Manual LED UAT checklist covering all 17 Phase 33 behaviors (incl. story-color spot-check), spidev smoke test added to verify_hardware.sh, and SPI speed tuning guidance embedded in config.py for on-device Option A/B fallback.

## What was built

- **deploy/led-uat-checklist.md** — Comprehensive manual UAT checklist with one row per Phase 33 behavior (16 behaviors + 1 story-color spot-check), each row specifying exact trigger API call, expected color/timing/brightness, and Pass/Fail + Notes columns. Includes environment header for recording final spidev node, tuned SPI speed, encoder variant, and level-shifter status.
- **scripts/verify_hardware.sh** — Added LED-26 spidev node + permissions smoke block: checks `/dev/spidev*` presence, `spi` group existence, and service-user write access to the SPI node. Updated INFRA-04 NOTE from "unverified" to "post-bring-up is_mock=false expected".
- **app/config.py** — Embedded on-device tuning guidance for `led_spi_speed_hz`: Option A (6.4 MHz) default with documented fallback to Option B (3.2 MHz) if strip rendering fails, referencing the UAT checklist.

## Deviations from Plan

None — plan executed exactly as written. Task 2 was a minimal documentation addition (tuning guidance comment) rather than an on-device value change, which is the correct scope for this dev-machine execution.
