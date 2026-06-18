---
gsd_state_version: 1.0
milestone: v1.5
milestone_name: Bluetooth Loudspeaker Connection
status: executing
stopped_at: context exhaustion at 76% (2026-06-17)
last_updated: "2026-06-18T16:25:10.181Z"
last_activity: 2026-06-18 -- Phase 27 execution started
progress:
  total_phases: 5
  completed_phases: 1
  total_plans: 11
  completed_plans: 10
  percent: 22
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-12, v1.5 Bluetooth started; history reconciled)

**Core value:** Children can hear AI-generated personalized stories and stories recorded by their teachers on demand.
**Current focus:** Phase 27 — pairing-audio-routing

## Current Position

Phase: 27 (pairing-audio-routing) — EXECUTING
Plan: 2 of 8 (27-07 complete, executing 27-08)
Status: Executing Phase 27
Last activity: 2026-06-18 -- Plan 27-07 complete (disconnect mac fix)

Progress: [██████████] 100%

## Reconciliation (2026-06-12)

Merged the second development machine's `.planning` (downloaded to `/tmp/.planning`) — which matches the committed code — with the local tree. Outcome:

- Adopted the second machine's real history as the base: **v1.3 Dispositivo Noia** (capability detection, phases 17-21, shipped) and **v1.4 WiFi Access** (phases 22-25, in progress).
- The Bluetooth milestone started locally on 2026-06-12 (originally labeled "v1.3") was re-slotted to **v1.5** to avoid colliding with the existing v1.3/v1.4. Phases stayed 26-30.
- **v1.4 WiFi is actually code-complete** (verified 2026-06-12: all 22-25 implemented, 156 WiFi/update tests pass). The imported snapshot was stale (2026-05-28, before the 2026-06-01 implementation). Only on-device/mobile UAT remains.
- Pre-reconciliation local tree backed up at `.planning.backup-pre-reconcile-20260612/` (and `.planning.oldbase/`). `.planning` is gitignored, so these backups are the only rollback path.

## Milestones at a glance

| Milestone | Phases | Status |
|-----------|--------|--------|
| v1.0 MVP | 00-06 | Shipped |
| v1.1 Quality | 07-11 | Shipped |
| v1.2 AI Story Generation | 12-16 | Shipped |
| v1.3 Dispositivo Noia | 17-21 | Shipped |
| v1.4 WiFi Access | 22-25 | Code complete (on-device UAT pending) |
| v1.5 Bluetooth Loudspeaker Connection | 26-30 | Active — planning |

## Accumulated Context

### Decisions

See PROJECT.md Key Decisions table.
Key decisions for v1.5 Bluetooth:

- dbus-fast for BlueZ D-Bus communication (replaces deprecated dbus-python)
- pactl subprocess for audio routing (works under both PulseAudio and PipeWire)
- BlueZ Agent1 with NoInputNoOutput capability for headless pairing
- HardwareService Real/Mock protocol pattern (consistent with WifiManager / printer)
- Single remembered speaker (N=1) stored in content/bt_devices.json (see 26-CONTEXT.md)

Recent decisions carried from v1.4 WiFi (paused):

- Zero new Python dependencies — subprocess wrappers around nmcli, git, uv, systemctl
- git fetch + git reset --hard origin/main for OTA (handles partial downloads)
- Health check + rollback on failed OTA update; delayed detached restart
- Polkit for passwordless nmcli, sudoers drop-in for passwordless systemctl restart
- [Phase 27]: 27-05: Real pair/connect/disconnect/forget each behind ONE patchable async seam; pair on shared SYSTEM bus (Pitfall 1); routing via bt_audio; forget clears store only on MAC match (Open Question 2)
- [Phase ?]: 27-06: BT POST endpoints are thin — delegate to manager and return its {ok:...} dict directly; used existing BtForgetText model name (surgical)

### Blockers/Concerns

- Phase 27: BlueZ Agent1 D-Bus service export via dbus-fast has thin documentation; may need a prototype spike during planning
- Phase 27: Jetson JetPack A2DP blocker (nv-bluetooth-service.conf) must be handled in deploy script
- Phase 28: systemd service ordering for pactl access within service context needs hardware validation
- v1.4 WiFi: code-complete and tests pass, but on-device/mobile UAT (teacher phone flows) + Jetson WiFi-hardware validation are unverified from the dev machine

## Deferred Items

Items carried forward from previous milestones:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Hardware | Jetson 10-iteration soak (D-14/D-15/D-17/D-18) | Pending physical hardware session | v1.2 close |
| Hardware | Brother QL sticker photo evidence (D-18) | Pending physical hardware session | v1.2 close |
| Deployment | llama-server sudoers NOPASSWD drop-in | Not blocking | v1.2 close |
| Process | Nyquist validation files for phases 12-15 | Structural gap, not functional | v1.2 close |
| Lint | Pre-existing warnings (E501, E402, F401, F841) | Cosmetic | v1.2 close |
| UAT | v1.4 WiFi/Updates on-device + mobile verification | Code complete; needs teacher-phone UAT + Jetson WiFi hardware test | v1.5 start |

## Session Continuity

Last session: 2026-06-18T12:57:29.094Z
Stopped at: context exhaustion at 76% (2026-06-17)
Resume file: .planning/phases/26-bt-service-foundation/26-CONTEXT.md

---
*STATE.md — Updated 2026-06-12: reconciled second-machine history, v1.5 Bluetooth active.*

## Performance Metrics

| Phase | Plan | Duration | Notes |
|-------|------|----------|-------|
| Phase 27 P27-05 | 00:08 | 2 tasks | 3 files |
| Phase 27 P27-06 | 00:12 | 1 tasks | 2 files |
| Phase 27 P27-07 | 00:05 | 2 tasks | 3 files |
