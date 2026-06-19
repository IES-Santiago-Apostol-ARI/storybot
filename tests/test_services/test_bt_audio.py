"""Tests for app/services/bt_audio.py — pactl audio routing (PLAT-02, AUDIO-01/02/06).

The whole module is exercised through the single `_run_pactl` subprocess seam: tests
patch either `asyncio.create_subprocess_exec` (for the `_run_pactl` unit tests) or
`bt_audio._run_pactl` itself (for the routing tests). No real pactl is ever spawned.
"""

from app.services import bt_audio


class _FakeProc:
    """Minimal stand-in for asyncio.subprocess.Process used by _run_pactl."""

    def __init__(self, stdout=b"", stderr=b"", returncode=0):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self):
        return self._stdout, self._stderr


def _patch_exec(monkeypatch, captured, *, stdout=b"", stderr=b"", returncode=0):
    """Patch asyncio.create_subprocess_exec to capture calls and return _FakeProc."""

    async def fake_exec(*args, **kwargs):
        captured.append({"args": args, "kwargs": kwargs})
        return _FakeProc(stdout, stderr, returncode)

    monkeypatch.setattr(bt_audio.asyncio, "create_subprocess_exec", fake_exec)


# --- Task 1: _run_pactl seam + MAC -> card/sink helpers ----------------------


def test_bt_card_name_uppercases_and_swaps_colons():
    assert bt_audio._bt_card("aa:bb:cc:00:11:22") == "bluez_card.AA_BB_CC_00_11_22"


def test_bt_card_name_preserves_already_upper_mac():
    # The legacy script's DEVICE is already upper-case; the helper must be idempotent.
    assert bt_audio._bt_card("00:42:79:E9:90:46") == "bluez_card.00_42_79_E9_90_46"


def test_bt_sink_name_format():
    assert (
        bt_audio._bt_sink("aa:bb:cc:00:11:22")
        == "bluez_output.AA_BB_CC_00_11_22.a2dp-sink"
    )


async def test_run_pactl_uses_pactl_binary_with_arg_list(monkeypatch):
    captured = []
    _patch_exec(monkeypatch, captured, stdout=b"ok\n", stderr=b"warn", returncode=0)
    out, err, rc = await bt_audio._run_pactl("list", "short", "sinks")
    # arg LIST (create_subprocess_exec, never shell=True): first arg is the binary
    assert captured[0]["args"][0] == "pactl"
    assert captured[0]["args"][1:] == ("list", "short", "sinks")
    # shell= must never be True (arg-injection control, PLAT-02 / T-27-01)
    assert captured[0]["kwargs"].get("shell") is not True
    # stdout/stderr decoded + stripped
    assert out == "ok"
    assert err == "warn"
    assert rc == 0


async def test_run_pactl_returncode_neg1_when_none(monkeypatch):
    captured = []
    _patch_exec(monkeypatch, captured, returncode=None)
    _, _, rc = await bt_audio._run_pactl("list", "short", "sinks")
    assert rc == -1


# --- Task 2: route_to_bt ordering + route_to_wired fallback -------------------


async def test_route_to_bt_order_profile_before_default(monkeypatch):
    """AUDIO-06 set-card-profile MUST precede AUDIO-01 set-default-sink."""
    calls = []

    async def fake_run(*args):
        calls.append(args)
        return ("", "", 0)

    monkeypatch.setattr(bt_audio, "_run_pactl", fake_run)
    result = await bt_audio.route_to_bt("AA:BB:CC:00:11:22")
    assert calls[0] == ("set-card-profile", "bluez_card.AA_BB_CC_00_11_22", "a2dp-sink")
    assert calls[1] == (
        "set-default-sink",
        "bluez_output.AA_BB_CC_00_11_22.a2dp-sink",
    )
    assert result is True


async def test_route_to_bt_returns_false_when_default_sink_fails(monkeypatch):
    calls = []

    async def fake_run(*args):
        calls.append(args)
        # set-card-profile succeeds, set-default-sink fails
        return ("", "", 1 if args[0] == "set-default-sink" else 0)

    monkeypatch.setattr(bt_audio, "_run_pactl", fake_run)
    result = await bt_audio.route_to_bt("AA:BB:CC:00:11:22")
    assert result is False


async def test_route_to_bt_isolated_by_patching_run_pactl(monkeypatch):
    """PLAT-02 seam: patching _run_pactl fully isolates route_to_bt (no subprocess)."""
    invoked = []

    async def fake_run(*args):
        invoked.append(args)
        return ("", "", 0)

    monkeypatch.setattr(bt_audio, "_run_pactl", fake_run)
    await bt_audio.route_to_bt("11:22:33:44:55:66")
    assert len(invoked) == 3  # set-card-profile + set-default-sink + set-sink-volume


async def test_route_to_bt_sets_sink_volume_to_max_on_connect(monkeypatch):
    """D-01: Assert set-sink-volume 100% is called after successful route_to_bt."""
    calls = []

    async def fake_run(*args):
        calls.append(args)
        return ("", "", 0)

    monkeypatch.setattr(bt_audio, "_run_pactl", fake_run)
    mac = "aa:bb:cc:00:11:22"
    result = await bt_audio.route_to_bt(mac)

    assert result is True
    assert ("set-sink-volume", bt_audio._bt_sink(mac), "100%") in calls


def test_first_alsa_sink_returns_name_of_first_alsa_line():
    out = (
        "0\tbluez_output.AA_BB_CC_00_11_22.a2dp-sink\tmodule-bluez5-device.c\t"
        "s16le 2ch 44100Hz\tSUSPENDED\n"
        "1\talsa_output.pci-0000_00_1b.0.analog-stereo\tmodule-alsa-card.c\t"
        "s16le 2ch 48000Hz\tRUNNING\n"
        "2\talsa_output.platform-snd_tegra.0.analog-stereo\tmodule-alsa-card.c\t"
        "s16le 2ch 44100Hz\tIDLE\n"
    )
    assert (
        bt_audio._first_alsa_sink(out) == "alsa_output.pci-0000_00_1b.0.analog-stereo"
    )


def test_first_alsa_sink_skips_bluez_output_lines():
    out = "0\tbluez_output.AA_BB_CC_00_11_22.a2dp-sink\tmod\tspec\tSUSPENDED\n"
    assert bt_audio._first_alsa_sink(out) is None


def test_first_alsa_sink_returns_none_when_empty():
    assert bt_audio._first_alsa_sink("") is None


async def test_route_to_wired_selects_first_alsa_sink(monkeypatch):
    calls = []
    sinks_out = (
        "0\tbluez_output.AA_BB_CC_00_11_22.a2dp-sink\tmod\tspec\tSUSPENDED\n"
        "1\talsa_output.pci-0000_00_1b.0.analog-stereo\tmod\tspec\tRUNNING\n"
    )

    async def fake_run(*args):
        calls.append(args)
        if args[0] == "list":
            return (sinks_out, "", 0)
        return ("", "", 0)  # set-default-sink success

    monkeypatch.setattr(bt_audio, "_run_pactl", fake_run)
    result = await bt_audio.route_to_wired()
    assert calls[-1] == (
        "set-default-sink",
        "alsa_output.pci-0000_00_1b.0.analog-stereo",
    )
    assert result is True


async def test_route_to_wired_returns_false_when_no_alsa_sink(monkeypatch):
    async def fake_run(*args):
        if args[0] == "list":
            return ("0\tbluez_output.X.a2dp-sink\tm\ts\tS\n", "", 0)
        return ("", "", 0)

    monkeypatch.setattr(bt_audio, "_run_pactl", fake_run)
    result = await bt_audio.route_to_wired()
    assert result is False
