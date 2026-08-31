# Kiosk JS harness

`tests/test_kiosk_generation_guard.py` runs `static/children/script.js` for real
in Node, on top of a minimal DOM stub, so kiosk regressions that involve state
across several card taps are caught.

The pre-existing kiosk tests (`tests/test_kiosk_param_toggle.py`) assert on the
*source text* with regexes. That cannot catch an interaction bug: the GO card
went permanently dead once a generation was interrupted, and every regex
assertion still passed.

- `dom.js`   — element/classList/document stubs
- `load.js`  — builds the sandbox, loads the real script, exposes `sandbox`,
               `calls` (recorded fetches) and `getEl`
