"""Card models for NFC card type system."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class CardType(str, Enum):
    """NFC card type."""

    STORY = "story"
    PARAMETER = "parameter"
    GO = "go"


class NFCCard(BaseModel):
    """Base NFC card model."""

    uid: str = Field(..., description="NFC card UID")
    type: CardType = Field(..., description="Card type")


class ParameterCard(NFCCard):
    """Parameter card with category, value, emoji, and label."""

    type: Literal[CardType.PARAMETER] = CardType.PARAMETER
    category: str = Field(..., description="Parameter category")
    value: str = Field(..., description="Parameter value")
    emoji: str = Field(..., description="Visual emoji")
    label: str = Field(..., description="Display label")


class GoCard(NFCCard):
    """Go card that triggers story generation."""

    type: Literal[CardType.GO] = CardType.GO


class CardCreateRequest(BaseModel):
    """Request to register a card."""

    uid: str = Field(..., min_length=1, description="NFC card UID")
    type: CardType = Field(..., description="Card type (parameter or go)")
    category: str | None = Field(
        None, description="Category (required for parameter)"
    )
    value: str | None = Field(
        None, description="Value (required for parameter)"
    )
    emoji: str | None = Field(
        None, description="Emoji (required for parameter)"
    )
    label: str | None = Field(
        None, description="Label (required for parameter)"
    )


class CardsListResponse(BaseModel):
    """List of registered cards with count."""

    cards: list[dict] = Field(..., description="List of cards")
    total: int = Field(..., description="Total number of cards")
