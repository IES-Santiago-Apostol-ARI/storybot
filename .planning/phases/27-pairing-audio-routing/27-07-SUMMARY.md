# Plan 27-07 Summary

## Objective
Close GAP 1 / CR-01 (criterion #4, requirement BT-05): in production the `/api/bt` router builds a fresh `RealBtManager` per request, so `disconnect()` was a no-op at the BlueZ layer — the speaker stayed connected while only `route_to_wired()` ran.

## What Was Done
1. **RED** (Task 1): Added cross-instance disconnect regression test in `TestRealDisconnect` that constructs two `RealBtManager` instances sharing one `BtDeviceStore`, proving `_disconnect_device` fires when given an explicit MAC on a fresh instance.
2. **GREEN** (Task 2): Changed `disconnect()` signature to accept optional `mac: str | None = None` on base class, `RealBtManager`, and `MockBtManager`. `RealBtManager.disconnect` resolves `target = mac or self._connected_mac` and gates `_disconnect_device(bus, target)` on `if target is not None:`. Router `disconnect_speaker` now accepts an optional `BtConnectRequest` body and passes `body.mac if body else None`.

## Files Changed
- `app/services/bt_manager.py` — disconnect signature + target resolution
- `app/routers/bt.py` — disconnect_speaker accepts optional BtConnectRequest body
- `tests/test_services/test_bt_manager.py` — cross-instance regression test (RED→GREEN)

## Verification
- All 128 BT tests pass (127 prior + 1 new)
- Black and ruff clean on both changed files
- CR-01 resolved: disconnect now works across per-request manager instances
