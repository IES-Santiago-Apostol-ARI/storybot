---
phase: 12-parameter-cards
slug: parameter-cards
status: validated
nyquist_compliant: false
wave_0_complete: true
created: "2026-05-06"
validated: "2026-05-06"
---

# Phase 12 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x |
| **Config file** | `pyproject.toml` (root) |
| **Quick run command** | `uv run pytest tests/test_card_model.py tests/test_cards_api.py tests/test_session.py tests/test_api/test_session.py -q` |
| **Full suite command** | `uv run pytest --tb=short` |
| **Estimated runtime** | ~18 seconds (43 phase-specific tests) |

## Sampling Rate

- **After every task commit:** Run quick command above
- **After every plan wave:** Run full suite
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 20 seconds

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 12-01-01 | 01 | 1 | CARD-01: Card type data model + migration | — | v1→v2 auto-migration, cards dict populated | unit | `uv run pytest tests/test_card_model.py::TestMigrationV1ToV2 -q` | ✅ | ✅ green (5 tests) |
| 12-01-02 | 01 | 1 | CARD-01: Card type data model + migration | — | get_card(), create_card(), delete_card() work | unit | `uv run pytest tests/test_card_model.py::TestGetCard -q` | ✅ | ✅ green (2 tests) |
| 12-01-03 | 01 | 1 | CARD-01: Card type data model + migration | — | StoryManager dual-index sync (assign_nfc, delete_story) | unit | `uv run pytest tests/test_card_model.py::TestAssignNfcAlsoUpdatesCards -q` | ✅ | ✅ green (2 tests) |
| 12-01-04 | 01 | 1 | CARD-01: Card type data model + migration | — | CardType enum, ParameterCard, GoCard validation | unit | `uv run pytest tests/test_card_model.py::TestParameterCard -q` | ✅ | ✅ green (3 tests) |
| 12-02-01 | 01 | 2 | CARD-02: Parameter card CRUD API | — | POST/GET/DELETE /api/cards with type filtering | unit | `uv run pytest tests/test_cards_api.py -q` | ✅ | ✅ green (10 tests) |
| 12-03-01 | 01 | 3 | CARD-03: NFC tap routing + enriched SSE | — | card_type field in all SSE events | unit | `uv run pytest tests/test_api/test_nfc.py -q` | ✅ | ⚠️ PARTIAL (7 tests, no card_type assertion) |
| 12-03-02 | 01 | 3 | CARD-04: Session buffer with timeout | — | SessionManager accumulation, timeout, go-card clearing | unit | `uv run pytest tests/test_session.py -q` | ✅ | ✅ green (8 tests) |
| 12-02-02 | 02 | 3 | CARD-04: Session API endpoint tested | — | GET /api/session returns correct state | integration | `uv run pytest tests/test_api/test_session.py -q` | ✅ | ✅ green (2 tests) |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ PARTIAL (exists but incomplete)*

## Gap Analysis

### Identified Gaps

| # | Requirement | Gap Type | Description | Suggested Fix |
|---|-------------|----------|-------------|---------------|
| 1 | AC-3: NFC tap routing with enriched SSE events | MISSING | No test asserts `card_type` field in SSE event payloads for story/parameter/go cards. Plan summary claims "All 7 NFC tests pass" but none verify the enrichment behavior. | Add assertions to `tests/test_api/test_nfc.py` that check `event["card_type"]` matches expected value per card type |
| 2 | AC-3: Unregistered cards include `card_type="unknown"` | MISSING | No test for unregistered/unknown NFC card handling in SSE events. | Add test case to `tests/test_api/test_nfc.py` with a UID not in any index |

### Gap Plan

**Gap 1 (AC-3 SSE enrichment):**
```python
# In tests/test_api/test_nfc.py — add after existing NFC tests:
async def test_story_card_sse_includes_card_type(client, story_manager):
    # Register a story card via NFC tap
    event = await read_nfc_cards(story_manager)
    assert "card_type" in event
    assert event["card_type"] == "story"

async def test_parameter_card_sse_enriched(client, story_manager):
    # Register parameter card, verify category/value/emoji/label in event
    ...

async def test_go_card_sse_card_type(client, story_manager):
    ...

async def test_unknown_card_returns_unknown_type(client, story_manager):
    ...
```

**Gap 2 (unknown card type):** Covered by Gap 1 suggestion.

## Wave 0 Requirements

- [x] `tests/test_card_model.py` — model validation, migration, CRUD (23 tests)
- [x] `tests/test_cards_api.py` — API endpoint coverage (10 tests)
- [x] `tests/test_session.py` — session buffer behavior (8 tests)
- [x] `tests/test_api/test_session.py` — session endpoint integration (2 tests)

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Visual: parameter chip layout and bounce-in animation on kiosk display | AC-2 (Plan 02) | Requires physical device / browser rendering | Open `static/children/index.html`, tap parameter cards, verify chip appearance and animation |
| Visual: go card thinking overlay animation | AC-2 (Plan 02) | Visual-only feedback, no API contract | Tap go card on kiosk, observe thinking overlay appears |
| End-to-end: full story recipe flow (tap params → go → generation) | Phase 13 dependency | Generation logic is in Phase 13 | Register parameter cards via admin UI, tap them on kiosk, tap go card — verify session accumulates correctly |

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify ⚠️ AC-3 has PARTIAL coverage (Gap #1)
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 20s

**Approval:** pending — Gap #1 must be filled before nyquist_compliant: true

## Validation Audit 2026-05-06

| Metric | Count |
|--------|-------|
| Gaps found | 2 (AC-3 SSE enrichment, unknown card type) |
| Resolved | 0 |
| Escalated to manual-only | 0 |
| Total tests run | 43 passed |
| Phase-specific files verified | 7/7 ✅ |

**Recommendation:** Fill Gap #1 by adding `card_type` assertions to NFC SSE event tests. This is the only blocker for nyquist compliance.
