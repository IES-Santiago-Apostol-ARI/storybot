"""Cards API endpoints for parameter and go card management."""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_story_manager
from app.models.card import CardCreateRequest, CardsListResponse
from app.routers.nfc import session_manager
from app.services.story_manager import StoryManager

router = APIRouter(prefix="/api", tags=["cards"])


@router.post("/cards", status_code=status.HTTP_201_CREATED)
async def create_card(
    request: CardCreateRequest,
    story_manager: StoryManager = Depends(get_story_manager),
) -> dict:
    """Register a new card (parameter or go type).

    Parameter cards require category, value, emoji, and label.
    Go cards require only uid.
    """
    card_data = {"uid": request.uid, "type": request.type.value}

    if request.type.value == "parameter":
        if not all([request.category, request.value, request.emoji, request.label]):
            raise HTTPException(
                status_code=422,
                detail="Parameter cards require category, value, emoji, and label",
            )
        card_data["category"] = request.category
        card_data["value"] = request.value
        card_data["emoji"] = request.emoji
        card_data["label"] = request.label

    try:
        return story_manager.create_card(card_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e


@router.get("/cards", response_model=CardsListResponse)
async def list_cards(
    type: str | None = Query(None, description="Filter by card type"),
    story_manager: StoryManager = Depends(get_story_manager),
) -> CardsListResponse:
    """List all registered cards, optionally filtered by type."""
    index = story_manager._load_index()
    cards = list(index.get("cards", {}).values())

    if type:
        cards = [c for c in cards if c.get("type") == type]

    return CardsListResponse(cards=cards, total=len(cards))


@router.delete("/cards/{uid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_card(
    uid: str,
    story_manager: StoryManager = Depends(get_story_manager),
) -> None:
    """Delete a non-story card by UID."""
    try:
        deleted = story_manager.delete_card(uid)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Card '{uid}' not found",
        )


@router.get("/session")
async def get_session() -> dict:
    """Return current session state with accumulated parameters."""
    return session_manager.get_session()
