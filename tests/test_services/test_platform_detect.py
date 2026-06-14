"""Tests for app.services.platform_detect (Plan 26-01, Task 2).

Covers D-08/D-09: detect_platform() returns jetson/rpi/generic and never
raises. The Jetson branch reuses capability_probe._jetson_marker_exists
rather than re-checking /etc/nv_tegra_release directly.
"""

from unittest.mock import patch

from app.services.platform_detect import detect_platform


class TestDetectPlatform:
    """detect_platform() 3-way detector."""

    def test_jetson_when_marker_present(self):
        with patch("app.services.platform_detect._jetson_marker_exists") as m:
            m.return_value = True
            assert detect_platform() == "jetson"

    def test_rpi_when_model_file_matches(self):
        with patch("app.services.platform_detect._jetson_marker_exists") as mj, \
             patch("app.services.platform_detect.Path") as mpath:
            mj.return_value = False
            model = mpath.return_value
            model.is_file.return_value = True
            model.read_text.return_value = "Raspberry Pi 4 Model B Rev 1.2"
            assert detect_platform() == "rpi"

    def test_rpi_match_is_case_insensitive(self):
        with patch("app.services.platform_detect._jetson_marker_exists") as mj, \
             patch("app.services.platform_detect.Path") as mpath:
            mj.return_value = False
            model = mpath.return_value
            model.is_file.return_value = True
            model.read_text.return_value = "RASPBERRY PI Compute Module 4"
            assert detect_platform() == "rpi"

    def test_generic_when_neither_marker_matches(self):
        with patch("app.services.platform_detect._jetson_marker_exists") as mj, \
             patch("app.services.platform_detect.Path") as mpath:
            mj.return_value = False
            model = mpath.return_value
            model.is_file.return_value = True
            model.read_text.return_value = "Generic x86 Desktop"
            assert detect_platform() == "generic"

    def test_generic_when_model_file_absent(self):
        with patch("app.services.platform_detect._jetson_marker_exists") as mj, \
             patch("app.services.platform_detect.Path") as mpath:
            mj.return_value = False
            model = mpath.return_value
            model.is_file.return_value = False
            assert detect_platform() == "generic"

    def test_generic_when_oserror_reading_model(self):
        """D-09: OSError on /proc read is non-fatal → 'generic'."""
        with patch("app.services.platform_detect._jetson_marker_exists") as mj, \
             patch("app.services.platform_detect.Path") as mpath:
            mj.return_value = False
            model = mpath.return_value
            model.is_file.return_value = True
            model.read_text.side_effect = OSError("permission denied")
            # Must NOT raise
            assert detect_platform() == "generic"

    def test_reuses_jetson_marker_helper(self):
        """PATTERNS constraint: reuse _jetson_marker_exists, don't duplicate the
        detection call (Path('/etc/nv_tegra_release').is_file())."""
        src = open("app/services/platform_detect.py").read()
        assert "_jetson_marker_exists" in src
        # Must not re-implement the marker check inline.
        assert 'Path("/etc/nv_tegra_release")' not in src
        assert "Path('/etc/nv_tegra_release')" not in src
