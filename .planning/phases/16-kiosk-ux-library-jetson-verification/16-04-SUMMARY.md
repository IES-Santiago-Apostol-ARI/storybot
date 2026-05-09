---
phase: 16-kiosk-ux-library-jetson-verification
plan: 04
subsystem: api, ui
tags: [printer, brother_ql, path-traversal, admin-ui, generated-stories, fastapi, vanilla-js]

# Dependency graph
requires:
  - phase: 16-01
    provides: PrinterService (RealPrinterService / MockPrinterService / create_printer_service factory) and app.state.printer lifespan wiring
  - phase: 16-03
    provides: GET /api/generated, DELETE /api/generated/{id}, POST /api/generated/{id}/promote endpoints and StoryManager generated methods
provides:
  - POST /api/printer/print endpoint with path-traversal guard (T-16-02)
  - Admin "Historias generadas" UI section with Preview / Discard / Promote→Asignar / Imprimir pegatina actions
  - Promote→Asignar chains into existing NFC-assign wizard via startNFCAssignment
affects: [admin-ui, printer-route, generated-stories]

# Tech tracking
tech-stack:
  added: []
  patterns: [path-traversal-guard, allowed-roots-whitelist, textContent-xss-prevention]

key-files:
  created:
    - app/routers/printer.py
  modified:
    - app/main.py
    - static/admin/index.html
    - static/admin/script.js
    - static/admin/styles.css
    - tests/test_api/test_printer_route.py

key-decisions:
  - "Print trigger is a dedicated button per story card — no auto-print on promote, no NFC coupling (RESEARCH §4 recommendation)"
  - "Test fixture restructured to set mock printer after TestClient lifespan runs, preventing lifespan overwrite of the mock"
  - "Admin UI reuses existing startNFCAssignment and showMessage functions — no duplication"

patterns-established:
  - "Allowed-roots whitelist pattern for file-serving routes: _ALLOWED_ROOTS + _validate_print_path with resolve + is_relative_to"
  - "Admin UI append-only pattern: new section + modal + JS functions added without modifying existing functions"

requirements-completed: [D-10, D-11, D-18]

# Metrics
duration: 17min
completed: 2026-05-09
---

# Phase 16 Plan 04: Printer Route + Admin Generated UI Summary

**Printer route POST /api/printer/print with path-traversal guard + admin "Historias generadas" section with promote/discard/print actions**

## Performance

- **Duration:** 17 min
- **Started:** 2026-05-09T19:40:26Z
- **Completed:** 2026-05-09T19:58:13Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- POST /api/printer/print endpoint validates paths under content/generated/ and content/stories/ only, rejects .. traversal and absolute paths
- Admin panel shows fourth "Historias generadas" section populated via GET /api/generated
- Each generated-story card exposes Vista previa, Imprimir pegatina, Promover → Asignar, Descartar actions
- Promote flow opens modal (title/emoji/LED color), POSTs promote, then chains into existing startNFCAssignment NFC wizard
- All Wave 0 RED printer stubs (test_printer_route.py) now GREEN

## Task Commits

Each task was committed atomically:

1. **Task 4.1: Implement /api/printer/print router with path-traversal guard** - `d33656f` (feat)
2. **Task 4.2: Admin Historias generadas UI section** - `1d7de26` (feat)

## Files Created/Modified
- `app/routers/printer.py` - POST /api/printer/print with PrintRequest model and _validate_print_path guard
- `app/main.py` - Register printer router (app.state.printer already wired by 16-01)
- `static/admin/index.html` - generated-section + promote-modal template
- `static/admin/script.js` - loadGeneratedStories, createGeneratedCard, submitPromote, printSticker, etc.
- `static/admin/styles.css` - .generated-section, .generated-card, .promote-modal styles
- `tests/test_api/test_printer_route.py` - Fixed fixture ordering for mock printer after lifespan

## Decisions Made
- Print trigger is a dedicated button (not auto-print on promote) — decoupled from NFC assignment flow per RESEARCH §4
- Test fixture restructured: mock printer set inside TestClient context (after lifespan) to prevent overwrite by create_printer_service()
- Admin UI uses textContent everywhere (never innerHTML) for XSS prevention (T-16-04-03 mitigation)
- Reused existing DOMContentLoaded listener instead of adding a second one

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed test fixture ordering in test_printer_route.py**
- **Found during:** Task 4.1 (GREEN phase)
- **Issue:** The mock_printer fixture set app.state.printer BEFORE TestClient entered the lifespan context. The lifespan then called create_printer_service() which overwrote the mock with a real MockPrinterService, causing assert_awaited_once() to fail on the wrong object.
- **Fix:** Merged mock_printer and client fixtures into a single client fixture that sets the AsyncMock AFTER TestClient enters (after lifespan completes), then yields both client and mock.
- **Files modified:** tests/test_api/test_printer_route.py
- **Verification:** All 4 TestPrintRoute tests pass
- **Committed in:** d33656f (Task 4.1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Necessary fix — test stubs had a fixture ordering bug that prevented GREEN. No scope creep.

## Issues Encountered
- Pre-existing test failure in tests/test_services/test_story_generator.py::test_streams_text (async generator TypeError) — unrelated to this plan, out of scope.

## User Setup Required

**External services require manual configuration.** See [16-USER-SETUP.md](./16-USER-SETUP.md) for:
- Jetson USB verification of Brother QL-820NWBc (lsusb check)

## Next Phase Readiness
- All Wave 0 RED stubs for printer route are GREEN
- Admin panel has four sections: Upload, Biblioteca, Tarjetas, Historias generadas
- Ready for 16-05 (Jetson verification + manual smoke test)
- D-12 invariant confirmed: /api/stories never returns generated entries (regression tests pass)

---
*Phase: 16-kiosk-ux-library-jetson-verification*
*Completed: 2026-05-09*

## Self-Check: PASSED

All key files exist on disk. Both task commits found in git log. All acceptance criteria verified.
