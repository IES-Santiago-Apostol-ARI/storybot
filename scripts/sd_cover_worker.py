#!/usr/bin/env python3
"""SD cover worker — generates cover images in an isolated subprocess.

Run via: ~/sd-cover/.venv/bin/python scripts/sd_cover_worker.py
Reads one JSON line from stdin, writes PNGs to out_dir, exits 0 on success.

This script imports NOTHING from the storybot app/ package (process isolation).
"""

import json
import sys
import time
from pathlib import Path

# --- Frozen pipeline config from 15-01 report.md ---

SD_MODEL = Path.home() / "sd-cover/models/stable-diffusion-v1-5"
LCM_LORA = Path.home() / "sd-cover/models/lcm-lora-sdv1-5"
LINEART = Path.home() / "sd-cover/models/lineart-loras/coloringbook-redmond-sd15"
LINEART_WEIGHTS = "ColoringBookRedmond15V-LiberteRedmond-ColoringBookAF.safetensors"

LCM_STEPS = 6
GUIDANCE_SCALE = 1.5
GEN_RESOLUTION = 512
OUTPUT_RESOLUTION = 696
THRESHOLD = 128
LINEART_WEIGHT = 0.9
LCM_WEIGHT = 1.0


def build_pipeline():
    import torch
    from diffusers import LCMScheduler, StableDiffusionPipeline

    pipe = StableDiffusionPipeline.from_pretrained(
        str(SD_MODEL),
        torch_dtype=torch.float16,
        safety_checker=None,
        requires_safety_checker=False,
    )
    pipe.load_lora_weights(str(LCM_LORA), adapter_name="lcm")
    pipe.load_lora_weights(
        str(LINEART), weight_name=LINEART_WEIGHTS, adapter_name="lineart"
    )
    pipe.set_adapters(["lcm", "lineart"], adapter_weights=[LCM_WEIGHT, LINEART_WEIGHT])
    pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)

    pipe.enable_vae_slicing()
    pipe.enable_vae_tiling()
    pipe.enable_attention_slicing(1)
    pipe.to("cuda")
    return pipe


def generate_cover(pipe, positive_prompt, negative_prompt, seed, out_dir):
    import torch
    from PIL import Image

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    result = pipe(
        prompt=positive_prompt,
        negative_prompt=negative_prompt,
        num_inference_steps=LCM_STEPS,
        guidance_scale=GUIDANCE_SCALE,
        width=GEN_RESOLUTION,
        height=GEN_RESOLUTION,
        generator=torch.Generator("cuda").manual_seed(seed),
    )
    img = result.images[0]
    if OUTPUT_RESOLUTION != GEN_RESOLUTION:
        img = img.resize((OUTPUT_RESOLUTION, OUTPUT_RESOLUTION), Image.LANCZOS)

    preview = out_dir / "cover-preview.png"
    img.save(preview)

    gray = img.convert("L")
    bw = gray.point(lambda p: 255 if p > THRESHOLD else 0).convert(
        "1", dither=Image.Dither.NONE
    )
    print_img = out_dir / "cover-print.png"
    bw.save(print_img)
    return preview, print_img


def main():
    try:
        payload = json.loads(sys.stdin.readline())
        positive_prompt = payload["positive_prompt"]
        negative_prompt = payload["negative_prompt"]
        seed = payload["seed"]
        out_dir = Path(payload["out_dir"])
    except (json.JSONDecodeError, KeyError) as e:
        json.dump(
            {"status": "error", "reason": "bad_payload", "detail": str(e)},
            sys.stderr,
        )
        sys.stderr.write("\n")
        sys.exit(1)

    try:
        t0 = time.time()
        pipe = build_pipeline()
        preview, print_path = generate_cover(
            pipe, positive_prompt, negative_prompt, seed, out_dir
        )
        gen_seconds = time.time() - t0

        json.dump(
            {
                "status": "ok",
                "preview": str(preview),
                "print": str(print_path),
                "gen_seconds": round(gen_seconds, 2),
            },
            sys.stdout,
        )
        sys.stdout.write("\n")
        sys.stdout.flush()
        sys.exit(0)
    except Exception as e:
        import traceback

        json.dump(
            {
                "status": "error",
                "reason": type(e).__name__,
                "detail": traceback.format_exc(),
            },
            sys.stderr,
        )
        sys.stderr.write("\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
