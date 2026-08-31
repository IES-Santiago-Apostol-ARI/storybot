"""Tests for SessionManager service."""

import time
from unittest.mock import patch

import pytest

from app.services.session_manager import SessionManager


@pytest.fixture
def session() -> SessionManager:
    """Create a SessionManager with short timeout for testing."""
    return SessionManager(timeout_seconds=2)


class TestSessionAddParameter:
    """Test SessionManager.add_parameter()."""

    def test_add_parameter_stores_parameter(self, session: SessionManager):
        card = {
            "uid": "11:22:33:44",
            "type": "parameter",
            "category": "character",
            "value": "dragon",
            "emoji": "🐉",
            "label": "Dragón",
        }
        result = session.add_parameter(card)

        assert len(result) == 1
        assert result[0]["category"] == "character"
        assert result[0]["value"] == "dragon"

    def test_add_parameter_accumulates_multiple(self, session: SessionManager):
        card1 = {
            "uid": "11:22:33:44",
            "type": "parameter",
            "category": "character",
            "value": "dragon",
            "emoji": "🐉",
            "label": "Dragón",
        }
        card2 = {
            "uid": "55:66:77:88",
            "type": "parameter",
            "category": "setting",
            "value": "forest",
            "emoji": "🌲",
            "label": "Bosque",
        }
        session.add_parameter(card1)
        result = session.add_parameter(card2)

        assert len(result) == 2
        assert result[0]["category"] == "character"
        assert result[1]["category"] == "setting"


class TestSessionParameterToggle:
    """Test parameter card toggle behavior (tap same card twice)."""

    def test_same_card_twice_removes_it(self, session: SessionManager):
        card1 = {
            "uid": "11:22:33:44",
            "type": "parameter",
            "category": "character",
            "value": "dragon",
            "emoji": "🐉",
            "label": "Dragón",
        }
        session.add_parameter(card1)
        result = session.add_parameter(card1)

        assert result == []

    def test_toggle_off_keeps_the_other_parameters_in_order(
        self, session: SessionManager
    ):
        card1 = {
            "uid": "11:22:33:44",
            "type": "parameter",
            "category": "character",
            "value": "dragon",
            "emoji": "🐉",
            "label": "Dragón",
        }
        card2 = {
            "uid": "55:66:77:88",
            "type": "parameter",
            "category": "setting",
            "value": "forest",
            "emoji": "🌲",
            "label": "Bosque",
        }
        card3 = {
            "uid": "99:AA:BB:CC",
            "type": "parameter",
            "category": "tone",
            "value": "funny",
            "emoji": "😄",
            "label": "Gracioso",
        }
        session.add_parameter(card1)
        session.add_parameter(card2)
        session.add_parameter(card3)
        result = session.add_parameter(card2)

        assert len(result) == 2
        assert result[0]["uid"] == "11:22:33:44"
        assert result[1]["uid"] == "99:AA:BB:CC"

    def test_retap_after_removal_adds_it_back(self, session: SessionManager):
        card1 = {
            "uid": "11:22:33:44",
            "type": "parameter",
            "category": "character",
            "value": "dragon",
            "emoji": "🐉",
            "label": "Dragón",
        }
        session.add_parameter(card1)
        session.add_parameter(card1)
        result = session.add_parameter(card1)

        assert len(result) == 1
        assert result[0]["uid"] == "11:22:33:44"

    def test_distinct_cards_sharing_a_value_are_independent(
        self, session: SessionManager
    ):
        card1 = {
            "uid": "11:22:33:44",
            "type": "parameter",
            "category": "character",
            "value": "owl",
            "emoji": "🦉",
            "label": "Búho",
        }
        card2 = {
            "uid": "55:66:77:88",
            "type": "parameter",
            "category": "character",
            "value": "owl",
            "emoji": "🦉",
            "label": "Búho",
        }
        session.add_parameter(card1)
        result = session.add_parameter(card2)

        assert len(result) == 2

    def test_toggle_off_refreshes_the_session_timeout(self, session: SessionManager):
        card1 = {
            "uid": "11:22:33:44",
            "type": "parameter",
            "category": "character",
            "value": "dragon",
            "emoji": "🐉",
            "label": "Dragón",
        }
        card2 = {
            "uid": "55:66:77:88",
            "type": "parameter",
            "category": "setting",
            "value": "forest",
            "emoji": "🌲",
            "label": "Bosque",
        }
        session.add_parameter(card1)
        session.add_parameter(card2)
        session.add_parameter(card2)

        result = session.get_session()
        assert result["is_active"] is True
        assert len(result["parameters"]) == 1


class TestSessionGetSession:
    """Test SessionManager.get_session()."""

    def test_get_session_empty(self, session: SessionManager):
        result = session.get_session()
        assert result["parameters"] == []
        assert result["is_active"] is False

    def test_get_session_with_params(self, session: SessionManager):
        card = {
            "uid": "11:22:33:44",
            "type": "parameter",
            "category": "character",
            "value": "dragon",
            "emoji": "🐉",
            "label": "Dragón",
        }
        session.add_parameter(card)
        result = session.get_session()

        assert len(result["parameters"]) == 1
        assert result["is_active"] is True


class TestSessionClear:
    """Test SessionManager.clear()."""

    def test_clear_empties_session(self, session: SessionManager):
        card = {
            "uid": "11:22:33:44",
            "type": "parameter",
            "category": "character",
            "value": "dragon",
            "emoji": "🐉",
            "label": "Dragón",
        }
        session.add_parameter(card)
        session.clear()

        result = session.get_session()
        assert result["parameters"] == []
        assert result["is_active"] is False


class TestSessionTimeout:
    """Test session auto-expiry."""

    def test_session_expires_after_timeout(self, session: SessionManager):
        card = {
            "uid": "11:22:33:44",
            "type": "parameter",
            "category": "character",
            "value": "dragon",
            "emoji": "🐉",
            "label": "Dragón",
        }
        session.add_parameter(card)

        # Simulate timeout by advancing last_tap
        with patch.object(time, "time", return_value=time.time() + 100):
            result = session.get_session()

        assert result["parameters"] == []
        assert result["is_active"] is False


class TestSessionGoCard:
    """Test go card behavior."""

    def test_go_card_returns_params_and_clears(self, session: SessionManager):
        card1 = {
            "uid": "11:22:33:44",
            "type": "parameter",
            "category": "character",
            "value": "dragon",
            "emoji": "🐉",
            "label": "Dragón",
        }
        card2 = {
            "uid": "55:66:77:88",
            "type": "parameter",
            "category": "setting",
            "value": "forest",
            "emoji": "🌲",
            "label": "Bosque",
        }
        session.add_parameter(card1)
        session.add_parameter(card2)

        params = session.get_and_clear()
        assert len(params) == 2

        result = session.get_session()
        assert result["parameters"] == []
        assert result["is_active"] is False

    def test_go_card_with_empty_session_returns_empty(self, session: SessionManager):
        params = session.get_and_clear()
        assert params == []
