"""Tests for deploy/generate-patched-capsule.sh release parameterisation.

The script pairs archived UEFI artifacts with an L4T BSP tree. Pairing a
release's artifacts with a different release's BSP silently produces a capsule
whose UEFI does not match the kernel/userspace on disk, so the release the
artifacts come from must be derived from the BSP rather than hardcoded.
"""

import pathlib
import subprocess

SCRIPT = pathlib.Path("deploy/generate-patched-capsule.sh")


def _script_text():
    return SCRIPT.read_text()


def _fake_bsp(tmp_path, minor):
    """Build a minimal Linux_for_Tegra tree advertising release 36.5.<minor>."""
    bsp = tmp_path / "Linux_for_Tegra"
    (bsp / "nv_tegra").mkdir(parents=True)
    (bsp / "flash.sh").write_text("#!/bin/bash\n")
    (bsp / "nv_tegra" / "bsp_version").write_text(
        "# comment line\n"
        "BSP_BRANCH=36\n"
        "BSP_MAJOR=5\n"
        f"BSP_MINOR={minor}\n"
        'BSP_VERSION="${BSP_BRANCH}.${BSP_MAJOR}.${BSP_MINOR}"\n'
    )
    return bsp


def _run(bsp, env=None):
    """Run the script non-root; it must resolve inputs before demanding root."""
    return subprocess.run(
        ["bash", str(SCRIPT), str(bsp)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", **(env or {})},
    )


def test_fw_dir_not_hardcoded():
    """FW_DIR must not pin a literal release directory."""
    txt = _script_text()
    assert (
        'FW_DIR="$SCRIPT_DIR/firmware/r36.5.0"' not in txt
    ), "FW_DIR still hardcodes r36.5.0"


def test_bup_restricted_to_one_board():
    """The BUP must target a single board, not every t23x spec.

    An unrestricted `l4t_generate_soc_bup.sh t23x` covers every AGX Orin and
    Orin Nano SKU, producing a 128 MB capsule that cannot be staged: the
    Jetson's ESP is only 63 MB. Restricting to the board actually booted
    yields ~37 MB. Verified on-device 2026-08-07.
    """
    code = [
        line
        for line in _script_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    invocations = [line for line in code if "l4t_generate_soc_bup.sh" in line]
    assert invocations, "BUP generation call not found"
    for line in invocations:
        assert "-b " in line, (
            f"BUP generated unrestricted ({line.strip()!r}) — the capsule will "
            "be ~128 MB and will not fit the 63 MB ESP"
        )


def test_release_autodetected_from_bsp(tmp_path):
    """A 36.5.2 BSP resolves to firmware/r36.5.2, not the r36.5.0 archive."""
    result = _run(_fake_bsp(tmp_path, 2))
    output = result.stdout + result.stderr
    assert (
        "firmware/r36.5.2" in output
    ), f"did not resolve r36.5.2 from the BSP; got:\n{output}"
    assert (
        "firmware/r36.5.0" not in output
    ), f"fell back to the r36.5.0 archive for a 36.5.2 BSP:\n{output}"


def test_missing_artifacts_for_detected_release_aborts(tmp_path):
    """No archive for the BSP's release is a hard error, never a silent fallback."""
    result = _run(_fake_bsp(tmp_path, 2))
    assert result.returncode != 0, "should abort when r36.5.2 artifacts are absent"
    assert "ERROR" in result.stdout + result.stderr


def test_release_override_is_honoured(tmp_path):
    """L4T_RELEASE overrides autodetection for a deliberate mismatch."""
    result = _run(_fake_bsp(tmp_path, 2), env={"L4T_RELEASE": "36.5.9"})
    output = result.stdout + result.stderr
    assert "firmware/r36.5.9" in output, f"override ignored; got:\n{output}"


def test_matching_release_passes_validation(tmp_path):
    """A 36.5.0 BSP matches the archive and proceeds as far as the root check."""
    result = _run(_fake_bsp(tmp_path, 0))
    output = result.stdout + result.stderr
    assert (
        "must run as root" in output
    ), f"expected validation to pass and stop at the root check; got:\n{output}"


def test_missing_bsp_version_aborts(tmp_path):
    """A BSP tree with no bsp_version cannot be paired blindly."""
    bsp = _fake_bsp(tmp_path, 0)
    (bsp / "nv_tegra" / "bsp_version").unlink()
    result = _run(bsp)
    assert result.returncode != 0
    assert "ERROR" in result.stdout + result.stderr
