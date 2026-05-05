---
phase: 10-test-coverage
slug: test-coverage
status: complete
nyquist_compliant: true
wave_0_complete: false
created: 2026-05-06
validated: 2026-05-06
---

# Phase 10 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x with asyncio plugin |
| **Config file** | `pyproject.toml` (root) |
| **Quick run command** | `uv run pytest tests/test_services/ -v --tb=short` |
| **Full suite command** | `uv run pytest --tb=short -q` |
| **Estimated runtime** | ~90 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_services/test_nfc.py tests/test_services/test_tts.py -v --tb=short`
- **Before `/gsd-verify-work`:** Full suite must be green (excluding pre-existing failures)
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 10-01-01 | 01 | 1 | AC-1: NFC test suite passes | — | All RealNFCService tests updated to match current `_callbacks` API | unit | `uv run pytest tests/test_services/test_nfc.py -v --tb=short` | ✅ | ✅ green (22 passed, 3 skipped) |
| 10-01-02 | 01 | 1 | AC-2: TTS test suite passes | — | All TTSEngine tests updated to match piper 1.4.1 API (`voice.synthesize`) | unit | `uv run pytest tests/test_services/test_tts.py -v --tb=short` | ✅ | ✅ green (17 passed) |
| 10-01-03 | 01 | 1 | AC-3: No regressions | — | Full suite at or above baseline pass count | regression | `uv run pytest --tb=short -q` | ✅ | ⚠️ partial (269 passed, 5 pre-existing failures in test_story_generator.py) |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky/partial*

---

## Wave 0 Requirements

- [ ] Existing infrastructure covers all phase requirements.
  - Phase 10 only modified existing tests; no new test files or fixtures were created.
  - Test framework (pytest) and config (`pyproject.toml`) already existed from prior phases.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| NFC hardware integration with real reader | AC-1 | Requires physical pcscd + NFC reader not available in CI/dev env | 3 tests marked `@pytest.mark.skipif(not nfc_available())` — verify manually on Jetson with card tap |

*Note: The 3 skipped tests (`test_real_nfc_service_start_polling_creates_thread`, `test_real_nfc_service_check_availability_with_nfc`, `test_real_nfc_service_check_availability_without_nfc`) require NFC hardware and are expected to be manual-only.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify commands
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references — N/A (no new infrastructure needed)
- [ ] No watch-mode flags — verified via `--tb=short`
- [x] Feedback latency < 90s

**Approval:** approved 2026-05-06

---

## Validation Audit 2026-05-06 (Reconstruction from Artifacts)

| Metric | Count |
|--------|-------|
| Gaps found | 1 |
| Resolved | 1 |
| Escalated | 0 |

**Gap:** AC-3 regression check — the summary claimed "138 total pass" but current suite has 269 tests (5 pre-existing failures in `test_story_generator.py` unrelated to Phase 10). The phase goal was met: NFC and TTS test suites are green with no regressions introduced by this phase.
