"""Cover prompt builder — CLIP-budget-safe prompts from session parameters."""

from pathlib import Path

STYLE_PREAMBLE = (
    "coloring book page, bold thick black outlines on white background, "
    "no color, no shading, no fill, simple flat shapes, uniform line weight, "
    "single clear cartoon subject centered with uncluttered background, "
    "suitable for children ages 3-7 to color with crayons, "
    "no text, no lettering, no human face details"
)

NEGATIVE_PROMPT = (
    "color, shading, gradient, gray, fill, painting, photorealistic, "
    "3d render, blurry, distorted face, ugly, deformed, scary, weapons, "
    "watermark, signature, text, letters, low quality, nsfw, gore, dark, horror"
)

MAX_CLIP_TOKENS = 75

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


def _sub_personaje(value: str) -> str:
    return f"cute cartoon {value}"


def _sub_lugar(value: str) -> str:
    return f"in a simple {value}"


def _sub_objeto(value: str) -> str:
    return f"holding/with a simple {value}"


def _sub_emocion(value: str) -> str:
    return f"looking {value}"


_SUBSTITUTION_MAP = {
    "personaje": _sub_personaje,
    "lugar": _sub_lugar,
    "objeto": _sub_objeto,
    "emoción": _sub_emocion,
}

_DROP_ORDER = ["lugar", "objeto", "emoción"]


def build(params: list[dict]) -> tuple[str, str]:
    """Build a CLIP-budget-safe cover prompt from session parameters.

    Args:
        params: List of parameter dicts with 'category' and 'value' keys.

    Returns:
        Tuple of (positive_prompt, negative_prompt).
    """
    if not params:
        return (STYLE_PREAMBLE, NEGATIVE_PROMPT)

    by_category: dict[str, list[str]] = {}
    for p in params:
        cat = p.get("category", "")
        val = p.get("value", "")
        if cat and val and cat in _SUBSTITUTION_MAP:
            by_category.setdefault(cat, []).append(val)

    category_phrases: dict[str, str] = {}
    for cat, values in by_category.items():
        category_phrases[cat] = _SUBSTITUTION_MAP[cat](values[0])

    subject_parts: list[str] = []
    if "personaje" in category_phrases:
        subject_parts.append(category_phrases["personaje"])

    for cat in ["lugar", "objeto", "emoción"]:
        if cat in category_phrases:
            subject_parts.append(category_phrases[cat])

    positive_subject = " ".join(subject_parts)
    if positive_subject:
        full_prompt = f"{STYLE_PREAMBLE}, {positive_subject}"
    else:
        full_prompt = STYLE_PREAMBLE

    for drop_cat in _DROP_ORDER:
        if _count_tokens(full_prompt) <= MAX_CLIP_TOKENS:
            break
        if drop_cat in category_phrases:
            phrase = category_phrases[drop_cat]
            subject_parts = [p for p in subject_parts if p != phrase]
            positive_subject = " ".join(subject_parts)
            full_prompt = (
                f"{STYLE_PREAMBLE}, {positive_subject}"
                if positive_subject
                else STYLE_PREAMBLE
            )

    if positive_subject and _count_tokens(full_prompt) > MAX_CLIP_TOKENS:
        full_prompt = STYLE_PREAMBLE

    return (full_prompt, NEGATIVE_PROMPT)
