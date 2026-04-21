"""Tests for session API endpoint."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_story_manager
from app.routers.cards import router
from app.routers.nfc import session_manager
from app.services.story_manager import StoryManager


@pytest.fixture
def mock_story_manager():
    manager = MagicMock(spec=StoryManager)
    return manager


@pytest.fixture
def app_with_session(mock_story_manager):
    test_app = FastAPI()
    test_app.include_router(router)

    async def override_sm():
        return mock_story_manager

    test_app.dependency_overrides[get_story_manager] = override_sm
    return test_app


class TestSessionEndpoint:
    """Test GET /api/session endpoint."""

    def test_session_returns_empty_initially(self, app_with_session):
        session_manager.clear()
        with TestClient(app_with_session) as client:
            response = client.get("/api/session")
            assert response.status_code == 200
            data = response.json()
            assert data["parameters"] == []
            assert data["is_active"] is False

    def test_session_returns_params_after_add(self, app_with_session):
        session_manager.clear()
        session_manager.add_parameter({
            "uid": "04:A3:5B:C2:D4:30",
            "category": "personaje",
            "value": "dragon",
            "emoji": "🐉",
            "label": "Dragón",
        })
        try:
            with TestClient(app_with_session) as client:
                response = client.get("/api/session")
                assert response.status_code == 200
                data = response.json()
                assert len(data["parameters"]) == 1
                assert data["parameters"][0]["value"] == "dragon"
                assert data["is_active"] is True
        finally:
            session_manager.clear()
