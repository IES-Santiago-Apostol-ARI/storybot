---
status: partial
phase: 34-on-device-jetson-validation-deployment
source: [34-VERIFICATION.md]
started: "2026-06-22T12:00:00Z"
updated: "2026-06-22T12:00:00Z"
---

## Current Test

[awaiting human testing]

## Tests

### 1. Node-confirm checkpoint — run install.sh SPI1 step on physical Jetson, reboot, confirm /dev/spidev* + is_mock=false
expected: /dev/spidev0.0 exists; getent group spi succeeds; sudo -u $INSTALL_USER test -w /dev/spidev0.0 passes; /api/system/status shows is_mock=false
result: [pending]

### 2. Visual UAT — run deploy/led-uat-checklist.md row-by-row on the wired WS2812B strip
expected: All 17 rows (16 behaviors + story-color spot-check) record Pass; tuned led_spi_speed_hz and confirmed node recorded in checklist header
result: [pending]

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
