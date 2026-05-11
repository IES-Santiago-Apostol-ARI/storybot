#!/usr/bin/env python3
"""Preview rendered cover prompts without generating an image.

Runs the same build() used in production against a small set of parameter
combos that mirror real session inputs, and prints the final positive prompt
plus its CLIP token count so you can eyeball the budget and the wording.

Usage:
  uv run python scripts/preview_prompts.py
  uv run python scripts/preview_prompts.py --custom personaje=dragon lugar=castle
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.cover_prompt_builder import (  # noqa: E402
    MAX_CLIP_TOKENS,
    _count_tokens,
    build,
)

SAMPLE_COMBOS = [
    [("personaje", "elephant")],
    [("personaje", "lion"), ("lugar", "jungle")],
    [("personaje", "fox"), ("lugar", "forest"), ("objeto", "kite")],
    [("personaje", "panda"), ("objeto", "balloon"), ("emoción", "happy")],
    [
        ("personaje", "rabbit"),
        ("lugar", "garden"),
        ("objeto", "carrot"),
        ("emoción", "curious"),
    ],
]


def render(params: list[tuple[str, str]]) -> None:
    param_dicts = [{"category": c, "value": v} for c, v in params]
    positive, negative = build(param_dicts)
    tokens = _count_tokens(positive)
    over = " OVER" if tokens > MAX_CLIP_TOKENS else ""
    label = " + ".join(f"{c}={v}" for c, v in params) or "(no params)"
    print(f"--- {label}  [{tokens}/{MAX_CLIP_TOKENS} tokens{over}] ---")
    print(positive)
    print()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--custom",
        nargs="*",
        metavar="cat=val",
        help="One-off prompt with custom category=value pairs",
    )
    parser.add_argument(
        "--show-negative",
        action="store_true",
        help="Also print the negative prompt once at the top",
    )
    args = parser.parse_args()

    if args.show_negative:
        _, negative = build([])
        print(f"NEGATIVE PROMPT ({_count_tokens(negative)} tokens):")
        print(negative)
        print()

    if args.custom:
        params = []
        for pair in args.custom:
            if "=" not in pair:
                sys.exit(f"bad custom pair: {pair!r} (expected cat=val)")
            cat, val = pair.split("=", 1)
            params.append((cat, val))
        render(params)
        return

    for combo in SAMPLE_COMBOS:
        render(combo)


if __name__ == "__main__":
    main()
