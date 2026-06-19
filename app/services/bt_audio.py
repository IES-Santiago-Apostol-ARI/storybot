"""Bluetooth audio routing via the ``pactl`` subprocess (PLAT-02, AUDIO-01/02/06).

Testable audio-routing layer that ports the proven ``scripts/bluetooth-connect.sh``
pactl incantation into a single patchable subprocess seam (``_run_pactl``), so audio
routing is unit-testable hardware-free. The manager (plan 05) orchestrates this module.

Structural clone of ``app/services/wifi_manager.py`` ``_run_nmcli`` for the subprocess
wrapper; ``_log_event`` mirrors the bt namespace. All pactl calls go through the one
``_run_pactl`` seam using an arg list (no shell expansion) — the arg-injection control
for the unauthenticated admin API (RESEARCH Security Domain, threat T-27-01).
"""

import asyncio
import json
import sys


async def _run_pactl(*args: str) -> tuple[str, str, int]:
    """Run a pactl command and return ``(stdout, stderr, returncode)``.

    Direct clone of ``wifi_manager._run_nmcli`` (swap binary ``nmcli`` -> ``pactl``).
    Uses ``create_subprocess_exec`` with an arg LIST — never invokes a shell — so a
    MAC/card/sink string can never break out into a shell (PLAT-02 / T-27-01).
    """
    proc = await asyncio.create_subprocess_exec(
        "pactl",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return (
        stdout.decode().strip(),
        stderr.decode().strip(),
        proc.returncode if proc.returncode is not None else -1,
    )


def _log_event(event: str, **kwargs: object) -> None:
    """Structured JSON log to stderr (same pattern as wifi_manager / bt_manager)."""
    print(
        json.dumps({"event": event, **kwargs}),
        file=sys.stderr,
    )


def _bt_card(mac: str) -> str:
    """PulseAudio/PipeWire BlueZ card name for a MAC (colons -> underscores, upper).

    Mirrors the legacy ``bluez_card.${DEVICE//:/_}`` from bluetooth-connect.sh.
    """
    return "bluez_card." + mac.upper().replace(":", "_")


def _bt_sink(mac: str) -> str:
    """PulseAudio/PipeWire BlueZ A2DP sink name for a MAC."""
    return "bluez_output." + mac.upper().replace(":", "_") + ".a2dp-sink"


def _first_alsa_sink(pactl_short_sinks_output: str) -> str | None:
    """Return the first wired (``alsa_output.*``) sink from ``pactl list short sinks``.

    Parses the tab-separated ``pactl list short sinks`` output and returns the sink
    name (2nd column) of the first line whose name starts with ``alsa_output.``,
    skipping any ``bluez_output.*`` (BT) line. Returns ``None`` when no wired sink is
    present — never raises (T-27-02 DoS mitigation: pure parser over bounded output).
    """
    for line in pactl_short_sinks_output.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        name = parts[1]
        if name.startswith("alsa_output."):
            return name
    return None


async def route_to_bt(mac: str) -> bool:
    """Route audio to a connected BT speaker (A2DP) — AUDIO-06 then AUDIO-01.

    Explicitly activates the A2DP card profile BEFORE setting the BT sink as default
    (JetPack ships A2DP off; the profile must be selected even after the deploy fix —
    AUDIO-06). Returns ``True`` when ``set-default-sink`` succeeds (rc == 0).
    """
    # AUDIO-06: activate the A2DP profile first.
    await _run_pactl("set-card-profile", _bt_card(mac), "a2dp-sink")
    # AUDIO-01: make the BT speaker the default output.
    _, _, rc = await _run_pactl("set-default-sink", _bt_sink(mac))
    if rc == 0:
        # D-01: drive output sink to 100% volume on connect.
        await _run_pactl("set-sink-volume", _bt_sink(mac), "100%")
    else:
        _log_event("bt_route_failed", mac=mac, rc=rc, target=_bt_sink(mac))
    return rc == 0


async def route_to_wired() -> bool:
    """Fall back to the first wired (3.5mm / on-board codec) ALSA sink — AUDIO-02.

    Discovers the wired sink dynamically via ``pactl list short sinks`` (never
    hardcoded — RESEARCH A5 / Anti-pattern line 331), then sets it default. Returns
    ``False`` when no wired sink is found.
    """
    out, _, _ = await _run_pactl("list", "short", "sinks")
    wired = _first_alsa_sink(out)
    if not wired:
        _log_event("bt_route_failed", reason="no_alsa_sink")
        return False
    _, _, rc = await _run_pactl("set-default-sink", wired)
    if rc != 0:
        _log_event("bt_route_failed", rc=rc, target=wired)
    return rc == 0
