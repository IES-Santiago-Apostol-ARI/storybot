"""RED tests for app.models.capability.CapabilityProfile (Plan 17-01 Task 2).

These tests exercise the CapabilityProfile Pydantic v2 model:
- Construction with all five fields
- Validation errors on missing fields
- model_dump() key surface (API-01 contract)
- D-05 reason enum acceptance
- JSON round-trip via model_dump_json / model_validate_json
"""

import pytest
from pydantic import ValidationError

from app.models.capability import CapabilityProfile


class TestCapabilityProfile:
    """Tests for the CapabilityProfile Pydantic v2 model."""

    def test_constructs_with_all_fields(self):
        """Model constructs with all five fields set (D-06 field set)."""
        profile = CapabilityProfile(
            ai_enabled=True,
            tts_available=True,
            cover_gen=True,
            printer=True,
            reason="auto-detect:cuda+ram-ok",
        )
        assert profile.ai_enabled is True
        assert profile.tts_available is True
        assert profile.cover_gen is True
        assert profile.printer is True
        assert profile.reason == "auto-detect:cuda+ram-ok"

    @pytest.mark.parametrize(
        "field_to_omit",
        ["ai_enabled", "tts_available", "cover_gen", "printer", "reason"],
    )
    def test_missing_required_field_raises_validation_error(self, field_to_omit):
        """Missing any of the five required fields raises ValidationError."""
        all_fields = {
            "ai_enabled": True,
            "tts_available": True,
            "cover_gen": True,
            "printer": True,
            "reason": "auto-detect:cuda+ram-ok",
        }
        del all_fields[field_to_omit]
        with pytest.raises(ValidationError):
            CapabilityProfile(**all_fields)

    def test_model_dump_keys(self):
        """model_dump() returns dict with exactly the five expected keys."""
        profile = CapabilityProfile(
            ai_enabled=False,
            tts_available=False,
            cover_gen=False,
            printer=False,
            reason="auto-detect:no-cuda",
        )
        dumped = profile.model_dump()
        expected_keys = {
            "ai_enabled",
            "tts_available",
            "cover_gen",
            "printer",
            "reason",
        }
        assert set(dumped.keys()) == expected_keys
        assert len(dumped) == 5

    @pytest.mark.parametrize(
        "reason",
        [
            "auto-detect:cuda+ram-ok",
            "auto-detect:no-cuda",
            "auto-detect:insufficient-ram",
            "auto-detect:no-cuda+insufficient-ram",
            "env-override:forced-on",
            "env-override:forced-off",
            "probe-error:RuntimeError",
        ],
    )
    def test_accepts_d05_reason_enum_strings(self, reason):
        """Every D-05 reason enum string is acceptable as reason value."""
        profile = CapabilityProfile(
            ai_enabled=True,
            tts_available=True,
            cover_gen=True,
            printer=True,
            reason=reason,
        )
        assert profile.reason == reason

    def test_json_round_trip(self):
        """model_dump_json() round-trips losslessly via model_validate_json()."""
        original = CapabilityProfile(
            ai_enabled=True,
            tts_available=True,
            cover_gen=True,
            printer=False,
            reason="env-override:forced-on",
        )
        json_str = original.model_dump_json()
        restored = CapabilityProfile.model_validate_json(json_str)
        assert restored == original
        assert restored.ai_enabled is True
        assert restored.printer is False
        assert restored.reason == "env-override:forced-on"
