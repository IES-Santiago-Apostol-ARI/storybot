#!/usr/bin/env python3
"""bench_sd.py — Stable Diffusion 1.5 + LCM LoRA + lineart LoRA benchmark harness.

Must run from ~/sd-cover/.venv, NOT storybot's uv venv.
Stacks LCM + a chosen lineart/coloring-book LoRA, generates at --gen-resolution,
resizes to --output-resolution (Brother QL 62 mm @ 300 dpi = 696 px), thresholds
to 1-bit B/W with no dither (sticker-ready), and saves preview + print pair.
Measures first-image latency, per-step time, peak RSS.
"""

import argparse
import gc
import json
import re
import sys
import threading
import time
from pathlib import Path


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Benchmark SD 1.5 + LCM + lineart LoRA on Jetson.",
    )
    parser.add_argument(
        "--prompts", required=True, type=Path, help="Path to prompts.md"
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path.home() / "sd-cover/models/stable-diffusion-v1-5",
        help="Local path to runwayml/stable-diffusion-v1-5",
    )
    parser.add_argument(
        "--lcm-lora-dir",
        type=Path,
        default=Path.home() / "sd-cover/models/lcm-lora-sdv1-5",
        help="Local path to latent-consistency/lcm-lora-sdv1-5",
    )
    parser.add_argument(
        "--lineart-loras-root",
        type=Path,
        default=Path.home() / "sd-cover/models/lineart-loras",
        help="Root directory containing lineart LoRA subdirectories (one per candidate).",
    )
    parser.add_argument(
        "--lineart-lora",
        required=True,
        type=str,
        help=(
            "Short name of the lineart LoRA candidate. Must match a subdir of "
            "--lineart-loras-root (e.g. 'coloringbook-redmond-sd15')."
        ),
    )
    parser.add_argument(
        "--lineart-weight",
        type=float,
        default=0.9,
        help="Adapter weight for the lineart LoRA in the stack (default 0.9).",
    )
    parser.add_argument("--lcm-steps", type=int, default=4)
    parser.add_argument("--guidance-scale", type=float, default=1.5)
    parser.add_argument(
        "--gen-resolution",
        type=int,
        default=640,
        choices=[512, 640, 704],
        help="Generation resolution (SD-friendly multiple of 64). Default 640.",
    )
    parser.add_argument(
        "--output-resolution",
        type=int,
        default=696,
        choices=[696, 1392],
        help=(
            "Final image side length in pixels. 696 = Brother QL 62 mm @ 300 dpi; "
            "1392 = high-res 600 dpi mode."
        ),
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=128,
        help="Threshold value (0-255) for 1-bit B/W conversion. Default 128.",
    )
    parser.add_argument(
        "--no-threshold",
        action="store_true",
        help="Debug: skip 1-bit print step, save preview only.",
    )
    parser.add_argument("--scheduler", default="lcm")
    parser.add_argument(
        "--cpu-offload",
        choices=["none", "model", "sequential"],
        default="none",
        help=(
            "CPU offload mode. Jetson has unified memory — 'none' avoids "
            "NvMap fragmentation from weight ping-pong. 'model' / 'sequential' "
            "kept for comparison on dev (discrete GPU). Default: none."
        ),
    )
    parser.add_argument(
        "--attention-slice",
        default="1",
        help=(
            "Attention slice size: 'auto' or an integer. '1' = most aggressive "
            "(smallest attention buffer). Default: 1."
        ),
    )
    parser.add_argument("--output", type=Path, default=None, help="Append JSON lines to this file")
    parser.add_argument("--image-output-dir", type=Path, default=Path("/tmp"))
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--prompt-ids",
        type=str,
        default=None,
        help="Comma-separated prompt IDs to run (e.g. '1,3'). Default: all",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Prompt loader — reads prompts.md with style preamble + numbered prompts
# ---------------------------------------------------------------------------

def load_prompts(path: Path) -> tuple[str, str, list[dict]]:
    """Parse prompts.md → (style_preamble, negative_prompt, [prompt_entries]).

    Format expected:
      Everything before the first `## prompt-` is the style preamble.
      A `## Negative prompt` section contains the negative prompt text.
      Each prompt-N section has a **Positive prompt:** code block.
    """
    text = path.read_text(encoding="utf-8")

    negative_prompt = ""
    neg_match = re.search(
        r"##\s+Negative\s+prompt\s*\n(.*?)(?=\n##|\Z)",
        text,
        re.DOTALL,
    )
    if neg_match:
        block = neg_match.group(1).strip()
        code_match = re.search(r"```[^\n]*\n(.*?)```", block, re.DOTALL)
        negative_prompt = code_match.group(1).strip() if code_match else block

    sections = re.split(r"^##\s+prompt-(\d+)\s*$", text, flags=re.MULTILINE)
    preamble = sections[0].strip()
    prompts = []
    for i in range(1, len(sections), 2):
        num = int(sections[i])
        body = sections[i + 1]
        m = re.search(
            r"\*\*Positive prompt:\*\*\s*```[^\n]*\n(.*?)```", body, re.DOTALL
        )
        if not m:
            print(
                f"WARNING: prompt-{num} has no **Positive prompt:** code block, skipping",
                file=sys.stderr,
            )
            continue
        positive_prompt = m.group(1).strip()
        prompts.append({"id": num, "positive_prompt": positive_prompt})

    prompts.sort(key=lambda p: p["id"])
    return preamble, negative_prompt, prompts


# ---------------------------------------------------------------------------
# RSS sampler — background thread reading /proc/self/status
# ---------------------------------------------------------------------------

class RSSSampler:
    def __init__(self):
        self.samples: list[int] = []
        self._stop = threading.Event()

    def _read_rss_kb(self) -> int:
        try:
            status = Path("/proc/self/status").read_text()
            for line in status.splitlines():
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
        except (FileNotFoundError, ValueError):
            pass
        return 0

    def run(self):
        while not self._stop.is_set():
            rss = self._read_rss_kb()
            if rss:
                self.samples.append(rss)
            self._stop.wait(0.25)

    def stop(self):
        self._stop.set()

    def peak_mb(self) -> float:
        return max(self.samples) / 1024 if self.samples else 0.0


# ---------------------------------------------------------------------------
# Pipeline setup
# ---------------------------------------------------------------------------

def _resolve_lineart_lora(root: Path, short_name: str) -> tuple[Path, str | None]:
    """Return (lora_dir, weight_filename_or_None).

    weight_filename is None when the dir contains diffusers' default
    `pytorch_lora_weights.safetensors` — load_lora_weights finds it automatically.
    Otherwise we pass the explicit filename (e.g. the artificialguybr LoRA's
    long custom filename).
    """
    lora_dir = root / short_name
    if not lora_dir.is_dir():
        raise FileNotFoundError(
            f"Lineart LoRA dir not found: {lora_dir}. "
            f"Run install_sd_cover.sh or pass --extra-lora to add it."
        )

    default = lora_dir / "pytorch_lora_weights.safetensors"
    if default.is_file():
        return lora_dir, None

    safetensors = sorted(lora_dir.glob("*.safetensors"))
    if not safetensors:
        raise FileNotFoundError(f"No *.safetensors in {lora_dir}")
    if len(safetensors) > 1:
        print(
            f"WARNING: multiple safetensors in {lora_dir}, picking {safetensors[0].name}",
            file=sys.stderr,
        )
    return lora_dir, safetensors[0].name


def build_pipeline(
    model_dir: Path,
    lcm_lora_dir: Path,
    lineart_lora_dir: Path,
    lineart_weight_name: str | None,
    lineart_weight: float,
    cpu_offload: str = "none",
    attention_slice: str = "1",
):
    import torch
    from diffusers import LCMScheduler, StableDiffusionPipeline

    print(f"Loading pipeline from {model_dir}...", file=sys.stderr)
    pipe = StableDiffusionPipeline.from_pretrained(
        str(model_dir),
        torch_dtype=torch.float16,
        safety_checker=None,
        requires_safety_checker=False,
    )

    print(f"Loading LCM LoRA from {lcm_lora_dir}...", file=sys.stderr)
    pipe.load_lora_weights(str(lcm_lora_dir), adapter_name="lcm")

    print(
        f"Loading lineart LoRA from {lineart_lora_dir}"
        + (f" (weight_name={lineart_weight_name})" if lineart_weight_name else "")
        + "...",
        file=sys.stderr,
    )
    if lineart_weight_name:
        pipe.load_lora_weights(
            str(lineart_lora_dir),
            weight_name=lineart_weight_name,
            adapter_name="lineart",
        )
    else:
        pipe.load_lora_weights(str(lineart_lora_dir), adapter_name="lineart")

    pipe.set_adapters(["lcm", "lineart"], adapter_weights=[1.0, lineart_weight])

    print("Setting LCMScheduler...", file=sys.stderr)
    pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)

    pipe.enable_vae_slicing()
    pipe.enable_vae_tiling()

    if attention_slice == "auto":
        pipe.enable_attention_slicing("auto")
    else:
        pipe.enable_attention_slicing(int(attention_slice))

    if cpu_offload == "model":
        pipe.enable_model_cpu_offload()
    elif cpu_offload == "sequential":
        pipe.enable_sequential_cpu_offload()
    else:
        pipe.to("cuda")

    print(
        f"Pipeline ready (offload={cpu_offload}, attention_slice={attention_slice}).",
        file=sys.stderr,
    )
    return pipe


# ---------------------------------------------------------------------------
# Per-prompt generation + post-processing
# ---------------------------------------------------------------------------

def run_generation(
    pipe,
    prompt_text: str,
    negative_prompt: str,
    num_steps: int,
    guidance_scale: float,
    gen_resolution: int,
    output_resolution: int,
    threshold: int,
    no_threshold: bool,
    seed: int,
    image_output_dir: Path,
    prompt_id: int,
    lora_short: str,
) -> dict:
    import torch
    from PIL import Image

    pre_rss_kb = 0
    try:
        status = Path("/proc/self/status").read_text()
        for line in status.splitlines():
            if line.startswith("VmRSS:"):
                pre_rss_kb = int(line.split()[1])
                break
    except (FileNotFoundError, ValueError):
        pass

    sampler = RSSSampler()
    sampler_thread = threading.Thread(target=sampler.run, daemon=True)
    sampler_thread.start()

    t_start = time.monotonic()
    result = pipe(
        prompt=prompt_text,
        negative_prompt=negative_prompt,
        num_inference_steps=num_steps,
        guidance_scale=guidance_scale,
        width=gen_resolution,
        height=gen_resolution,
        generator=torch.Generator("cuda").manual_seed(seed),
    )

    image = result.images[0]
    raw_path = image_output_dir / f"bench-sd-prompt-{prompt_id}-{lora_short}-raw.png"
    image.save(str(raw_path))

    if output_resolution != gen_resolution:
        image = image.resize((output_resolution, output_resolution), Image.LANCZOS)

    preview_path = image_output_dir / f"bench-sd-prompt-{prompt_id}-{lora_short}-preview.png"
    image.save(str(preview_path))

    print_path: Path | None = None
    if not no_threshold:
        gray = image.convert("L")
        bw = gray.point(lambda p: 255 if p > threshold else 0).convert(
            "1", dither=Image.Dither.NONE
        )
        print_path = image_output_dir / f"bench-sd-prompt-{prompt_id}-{lora_short}-print.png"
        bw.save(str(print_path))

    t_end = time.monotonic()

    sampler.stop()
    sampler_thread.join(timeout=2)

    elapsed_ms = (t_end - t_start) * 1000
    per_step_ms = elapsed_ms / num_steps if num_steps > 0 else 0
    peak_ram_mb = (max(sampler.samples) - pre_rss_kb) / 1024 if sampler.samples else 0.0

    del result
    torch.cuda.empty_cache()
    gc.collect()

    return {
        "prompt_id": prompt_id,
        "lineart_lora": lora_short,
        "first_image_ms": round(elapsed_ms, 1),
        "per_step_ms": round(per_step_ms, 1),
        "peak_ram_mb": round(peak_ram_mb, 1),
        "lcm_steps": num_steps,
        "gen_resolution": gen_resolution,
        "output_resolution": output_resolution,
        "threshold": None if no_threshold else threshold,
        "guidance_scale": guidance_scale,
        "raw_path": str(raw_path),
        "preview_path": str(preview_path),
        "print_path": str(print_path) if print_path else None,
    }


# ---------------------------------------------------------------------------
# Summary aggregation
# ---------------------------------------------------------------------------

def summarize(results: list[dict], lineart_lora: str, threshold: int | None) -> dict:
    latencies = sorted(r["first_image_ms"] for r in results)
    steps = [r["per_step_ms"] for r in results]
    rams = [r["peak_ram_mb"] for r in results]

    p50 = latencies[len(latencies) // 2] if latencies else None
    p95_idx = int(len(latencies) * 0.95)
    p95 = latencies[min(p95_idx, len(latencies) - 1)] if latencies else None

    return {
        "p50_first_image_ms": round(p50, 1) if p50 is not None else None,
        "p95_first_image_ms": round(p95, 1) if p95 is not None else None,
        "mean_per_step_ms": round(sum(steps) / len(steps), 1) if steps else None,
        "max_peak_ram_mb": round(max(rams), 1) if rams else None,
        "n_runs": len(results),
        "lineart_lora": lineart_lora,
        "threshold": threshold,
    }


# ---------------------------------------------------------------------------
# Output helper
# ---------------------------------------------------------------------------

def emit(obj: dict, output: Path | None):
    line = json.dumps(obj, ensure_ascii=False)
    print(line, flush=True)
    if output:
        with open(output, "a", encoding="utf-8") as f:
            f.write(line + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = _parse_args()

    import torch
    if not torch.cuda.is_available():
        print("ERROR: CUDA not available. This benchmark requires a GPU.", file=sys.stderr)
        sys.exit(1)

    lineart_lora_dir, lineart_weight_name = _resolve_lineart_lora(
        args.lineart_loras_root, args.lineart_lora
    )

    style_preamble, negative_prompt, prompts = load_prompts(args.prompts)
    if not prompts:
        print("ERROR: No prompts found in", args.prompts, file=sys.stderr)
        sys.exit(1)

    if args.prompt_ids:
        ids = {int(x.strip()) for x in args.prompt_ids.split(",")}
        prompts = [p for p in prompts if p["id"] in ids]
        print(f"Filtered to {len(prompts)} prompt(s): {ids}", file=sys.stderr)

    print(
        f"Loaded {len(prompts)} prompts. Negative prompt: {len(negative_prompt)} chars. "
        f"Lineart LoRA: {args.lineart_lora} (weight {args.lineart_weight}).",
        file=sys.stderr,
    )

    pipe = build_pipeline(
        args.model_dir,
        args.lcm_lora_dir,
        lineart_lora_dir,
        lineart_weight_name,
        args.lineart_weight,
        cpu_offload=args.cpu_offload,
        attention_slice=args.attention_slice,
    )

    if args.warmup > 0:
        print(f"Warmup: {args.warmup} generation(s)...", file=sys.stderr)
        for _ in range(args.warmup):
            import torch as _t
            _result = pipe(
                prompt="coloring book page line art of a friendly cat, bold black outlines on white",
                negative_prompt=negative_prompt,
                num_inference_steps=args.lcm_steps,
                guidance_scale=args.guidance_scale,
                width=args.gen_resolution,
                height=args.gen_resolution,
                generator=_t.Generator("cuda").manual_seed(0),
            )
            del _result
        torch.cuda.empty_cache()
        gc.collect()

    args.image_output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    for prompt in prompts:
        print(f"Running prompt-{prompt['id']} with {args.lineart_lora}...", file=sys.stderr)
        result = run_generation(
            pipe=pipe,
            prompt_text=prompt["positive_prompt"],
            negative_prompt=negative_prompt,
            num_steps=args.lcm_steps,
            guidance_scale=args.guidance_scale,
            gen_resolution=args.gen_resolution,
            output_resolution=args.output_resolution,
            threshold=args.threshold,
            no_threshold=args.no_threshold,
            seed=args.seed,
            image_output_dir=args.image_output_dir,
            prompt_id=prompt["id"],
            lora_short=args.lineart_lora,
        )
        results.append(result)
        emit(result, args.output)

    summary = summarize(
        results,
        lineart_lora=args.lineart_lora,
        threshold=None if args.no_threshold else args.threshold,
    )
    emit({"summary": summary}, args.output)

    print(f"\nDone. {len(results)} images generated.", file=sys.stderr)


if __name__ == "__main__":
    main()
