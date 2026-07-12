#!/usr/bin/env python3
"""fuse_sd_loras.py — one-off: bake the LCM + lineart LoRAs into a fused
SD 1.5 checkpoint so the cover worker skips all LoRA work at cover time
(IMPROVEMENTS.md 3.5).

Run via the SD venv (same one the worker uses):
    ~/sd-cover/.venv/bin/python scripts/fuse_sd_loras.py

Writes ~/sd-cover/models/sd15-storybot-fused (fp16, safetensors). The worker
(scripts/sd_cover_worker.py) picks it up automatically when it exists.

Loads on CPU: fusing is a one-time weight merge, no CUDA needed, and staying
off the GPU means it can run while llama-server is up.
"""

import sys
import time
from pathlib import Path

# Must mirror the frozen pipeline config in scripts/sd_cover_worker.py.
SD_MODEL = Path.home() / "sd-cover/models/stable-diffusion-v1-5"
LCM_LORA = Path.home() / "sd-cover/models/lcm-lora-sdv1-5"
LINEART = Path.home() / "sd-cover/models/lineart-loras/coloringbook-redmond-sd15"
LINEART_WEIGHTS = "ColoringBookRedmond15V-LiberteRedmond-ColoringBookAF.safetensors"
LINEART_WEIGHT = 0.9
LCM_WEIGHT = 1.0

FUSED_OUT = Path.home() / "sd-cover/models/sd15-storybot-fused"


def main():
    import torch
    from diffusers import StableDiffusionPipeline

    if (FUSED_OUT / "model_index.json").exists():
        print(f"Fused checkpoint already exists at {FUSED_OUT} — nothing to do.")
        return

    t0 = time.time()
    print(f"Loading base pipeline from {SD_MODEL} (CPU, fp16)...")
    pipe = StableDiffusionPipeline.from_pretrained(
        str(SD_MODEL),
        torch_dtype=torch.float16,
        safety_checker=None,
        requires_safety_checker=False,
    )
    print(f"Loaded in {time.time() - t0:.1f}s. Fusing LoRAs...")

    pipe.load_lora_weights(str(LCM_LORA), adapter_name="lcm")
    pipe.load_lora_weights(
        str(LINEART), weight_name=LINEART_WEIGHTS, adapter_name="lineart"
    )
    pipe.set_adapters(["lcm", "lineart"], adapter_weights=[LCM_WEIGHT, LINEART_WEIGHT])
    pipe.fuse_lora(adapter_names=["lcm", "lineart"])
    pipe.unload_lora_weights()

    print(f"Fused in {time.time() - t0:.1f}s. Saving to {FUSED_OUT}...")
    pipe.save_pretrained(str(FUSED_OUT), safe_serialization=True)
    print(f"Done in {time.time() - t0:.1f}s total.")
    print("The cover worker will now load the fused checkpoint automatically.")


if __name__ == "__main__":
    sys.exit(main())
