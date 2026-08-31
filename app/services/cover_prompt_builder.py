"""Cover prompt builder — CLIP-budget-safe prompts from session parameters."""

import random
import unicodedata
from pathlib import Path

STYLE_HEAD = (
    "children's coloring book page, simple shapes, thick bold outlines, "
    "minimal details, black and white line art, easy coloring page, "
    "white background, "
)
STYLE_TAIL = "no shading, no fill, no text, for ages 2-8"

DEFAULT_COMPOSITION = "single subject centered"

STYLE_PREAMBLE = f"{STYLE_HEAD}{DEFAULT_COMPOSITION}, {STYLE_TAIL}"

NEGATIVE_PROMPT = (
    "shading, grayscale, shadow, realistic, photorealistic, "
    "crosshatching, sketch, painting, texture, background clutter, "
    "tiny details, text, watermark, color, dark background, "
    "scary, creepy, sharp teeth, fangs, claws, angry, "
    "deformed, ugly, distorted, blurry, low quality, nsfw"
)

# LCM at 6 steps / CFG 1.5 barely reacts to the seed, so a fixed prompt gave
# the same drawing for every story. These two pools move the pose and the
# framing, which is what actually changes the picture. Both are short (2-4
# CLIP tokens) so they rarely cost a parameter its place in the budget.
POSE_VARIANTS = (
    "standing",
    "sitting",
    "walking",
    "jumping",
    "waving hello",
    "dancing",
    "running",
    "sleeping",
    "playing",
)

COMPOSITION_VARIANTS = (
    DEFAULT_COMPOSITION,
    "full body, centered",
    "full body, side view",
    "three quarter view",
    "close-up portrait",
)

MAX_CLIP_TOKENS = 75

# Beyond three the drawing turns into a crowd of unrecognisable blobs.
MAX_CHARACTERS = 3

SD_MODEL_PATH = Path.home() / "sd-cover/models/stable-diffusion-v1-5"

_TOKENIZER = None


def _get_tokenizer():
    global _TOKENIZER
    if _TOKENIZER is not None:
        return _TOKENIZER
    try:
        from transformers import CLIPTokenizer

        _TOKENIZER = CLIPTokenizer.from_pretrained(
            str(SD_MODEL_PATH), subfolder="tokenizer"
        )
    except Exception:
        _TOKENIZER = None
    return _TOKENIZER


def _count_tokens(text: str) -> int:
    tokenizer = _get_tokenizer()
    if tokenizer is not None:
        ids = tokenizer.encode(text, truncation=False)
        return len(ids) - 2
    return len(text.split())


def _normalize_category(value: str) -> str:
    """Fold case, whitespace and accents on a category name.

    Cards are typed by hand in the admin panel, so real data carries both
    "Personaje" and "personaje" (content/stories/stories.json). A
    case-sensitive lookup silently dropped every capitalised card, which is
    why two-character stories drew only the first character.
    """
    folded = unicodedata.normalize("NFD", value.strip().casefold())
    return "".join(c for c in folded if not unicodedata.combining(c))


def _join_characters(values: list[str]) -> str:
    if len(values) == 1:
        return values[0]
    return f"{', '.join(values[:-1])} and {values[-1]}"


def _sub_personaje(values: list[str], pose: str) -> str:
    subject = _join_characters(values)
    if pose:
        return f"cute cartoon {subject} {pose}, with a friendly smile"
    return f"cute cartoon {subject} with a friendly smile"


def _sub_lugar(value: str) -> str:
    return f"in a simple {value}"


def _sub_objeto(value: str) -> str:
    return f"holding/with a simple {value}"


def _sub_emocion(value: str) -> str:
    return f"looking {value}"


# Modifier categories keep their first value only — "in a simple castle and
# forest" reads as neither place to the model.
_MODIFIER_SUBS = {
    "lugar": _sub_lugar,
    "objeto": _sub_objeto,
    "emocion": _sub_emocion,
}

_KNOWN_CATEGORIES = {"personaje", *_MODIFIER_SUBS}

_DROP_ORDER = ["lugar", "objeto", "emocion"]


def build(params: list[dict], *, rng: random.Random | None = None) -> tuple[str, str]:
    """Build a CLIP-budget-safe cover prompt from session parameters.

    The pose and the framing are drawn at random on every call, so the same
    parameters do not produce the same drawing twice.

    Args:
        params: List of parameter dicts with 'category' and 'value' keys.
        rng: Source of the pose/framing choice. Defaults to the ``random``
            module; pass a ``random.Random`` to make a prompt reproducible.

    Returns:
        Tuple of (positive_prompt, negative_prompt).
    """
    chooser = rng if rng is not None else random

    by_category: dict[str, list[str]] = {}
    for p in params:
        cat = _normalize_category(p.get("category", "") or "")
        val = (p.get("value", "") or "").strip()
        if cat and val and cat in _KNOWN_CATEGORIES:
            by_category.setdefault(cat, []).append(val)

    if not by_category:
        return (STYLE_PREAMBLE, NEGATIVE_PROMPT)

    pose = chooser.choice(POSE_VARIANTS)
    composition = chooser.choice(COMPOSITION_VARIANTS)

    characters = by_category.get("personaje", [])[:MAX_CHARACTERS]
    modifiers = [cat for cat in _DROP_ORDER if cat in by_category]

    def render() -> str:
        parts: list[str] = []
        if characters:
            parts.append(_sub_personaje(characters, pose))
        for cat in modifiers:
            parts.append(_MODIFIER_SUBS[cat](by_category[cat][0]))
        subject = " ".join(parts)
        if not subject:
            return STYLE_PREAMBLE
        return f"{subject}, {STYLE_HEAD}{composition}, {STYLE_TAIL}"

    # Reduction ladder, cheapest content first: place, object, emotion, then
    # the pose, then the extra characters. The leading character always stays.
    full_prompt = render()
    for drop_cat in list(_DROP_ORDER):
        if _count_tokens(full_prompt) <= MAX_CLIP_TOKENS:
            break
        if drop_cat in modifiers:
            modifiers.remove(drop_cat)
            full_prompt = render()

    if _count_tokens(full_prompt) > MAX_CLIP_TOKENS and pose:
        pose = ""
        full_prompt = render()

    while _count_tokens(full_prompt) > MAX_CLIP_TOKENS and len(characters) > 1:
        characters = characters[:-1]
        full_prompt = render()

    if full_prompt != STYLE_PREAMBLE and _count_tokens(full_prompt) > MAX_CLIP_TOKENS:
        full_prompt = STYLE_PREAMBLE

    return (full_prompt, NEGATIVE_PROMPT)
