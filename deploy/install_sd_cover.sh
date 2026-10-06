#!/usr/bin/env bash
# install_sd_cover.sh — Reproducible Jetson setup for SD 1.5 + LCM LoRA
# Target: Jetson Orin Nano Super 8GB, aarch64. Two supported stacks:
#   - JetPack 7 (CUDA 13, Python 3.12): upstream PyTorch cu132 wheels. Orin runs
#     the SBSA CUDA stack there, so torch + torchvision install straight from
#     download.pytorch.org — no NVIDIA wheel, no cuSPARSELt, no source build.
#   - JetPack 6 (CUDA 12.6, Python 3.10): NVIDIA's torch wheel + torchvision
#     built from source.
# Creates an ISOLATED venv at ~/sd-cover/ — must NOT run inside storybot's venv.
# Idempotent: every step is skipped when its result is already in place.
set -euo pipefail

SD_DIR="$HOME/sd-cover"
VENV_DIR="$SD_DIR/.venv"
MODELS_DIR="$SD_DIR/models"
SD_MODEL="$MODELS_DIR/stable-diffusion-v1-5"
LCM_LORA="$MODELS_DIR/lcm-lora-sdv1-5"
LINEART_DIR="$MODELS_DIR/lineart-loras"
VERSIONS_FILE="$SD_DIR/versions.txt"
USE_SYSTEM_TORCH=false

# Verified SD 1.5 lineart / coloring-book LoRA candidates (web-search verified 2026-04-26).
# Format: "<short-name>=<hf-repo>". Short name is the local subdir under
# ~/sd-cover/models/lineart-loras/ AND the value passed to bench_sd.py --lineart-lora.
# All entries MUST be SD 1.5 base (stable-diffusion-v1-5/stable-diffusion-v1-5), NOT SDXL/2.1.
LINEART_LORAS=(
  "coloringbook-redmond-sd15=artificialguybr/coloringbook-redmond-1-5v-coloring-book-lora-for-liberteredmond-sd-1-5"
  "sketch-sd15=jordanhilado/sd-1-5-sketch-lora"
)

# Args: --system-torch and zero-or-more --extra-lora <short=hf-repo>.
while [[ $# -gt 0 ]]; do
  case "$1" in
    --system-torch)
      USE_SYSTEM_TORCH=true
      shift
      ;;
    --extra-lora)
      if [[ -z "${2:-}" || "$2" != *"="* ]]; then
        echo "⛔ --extra-lora requires <short-name>=<hf-repo>, e.g. --extra-lora my-lora=user/repo"
        exit 1
      fi
      LINEART_LORAS+=("$2")
      shift 2
      ;;
    *)
      echo "⛔ Unknown arg: $1"
      echo "Usage: $0 [--system-torch] [--extra-lora <short=hf-repo> ...]"
      exit 1
      ;;
  esac
done

# ── Architecture check ──────────────────────────────────────────────────────
arch=$(uname -m)
if [[ "$arch" != "aarch64" ]]; then
  echo "⚠  Not running on aarch64 (detected: $arch). Some steps will be skipped."
  echo "   This is fine for a dev-machine dry-run."
fi

# ── CUDA stack detection (picks the torch source and the venv Python) ───────
CUDA_MAJOR=$(find /usr/local -maxdepth 1 -name 'cuda-[0-9]*' 2>/dev/null \
  | sed -n 's|.*/cuda-\([0-9][0-9]*\).*|\1|p' | sort -n | tail -1)
SBSA_TORCH=false
PY_VERSION="3.10"
if [[ "$arch" == "aarch64" && "${CUDA_MAJOR:-0}" -ge 13 ]]; then
  SBSA_TORCH=true
  PY_VERSION="3.12"
fi
# Upstream wheels for the CUDA 13 stack (pair confirmed on-device 2026-10-06).
SBSA_TORCH_INDEX="https://download.pytorch.org/whl/cu132"
SBSA_TORCH_VERSION="2.12.1"
SBSA_TORCHVISION_VERSION="0.27.1"

# ── Safety gate: must not run inside storybot's venv ────────────────────────
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  # Check if the active venv is inside the storybot repo
  repo_root="$(cd "$(dirname "$0")/.." && pwd)"
  if [[ "$VIRTUAL_ENV" == "$repo_root"* ]]; then
    echo "══════════════════════════════════════════════════════════════"
    echo "⛔  ABORTING: storybot's uv venv is active at $VIRTUAL_ENV"
    echo ""
    echo "SD's torch/diffusers must NOT contaminate storybot's pyproject.toml."
    echo "Deactivate it first:"
    echo "  deactivate"
    echo "  bash deploy/install_sd_cover.sh"
    echo "══════════════════════════════════════════════════════════════"
    exit 1
  fi
fi

# ── Step 1: Ensure uv is installed ──────────────────────────────────────────
echo ""
echo "Step 1: Check uv"
if command -v uv &>/dev/null; then
  echo "  ✓ uv found: $(uv --version)"
else
  echo "  ⚠  uv not found. Install it:"
  echo "     curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo "     Then re-run this script."
  exit 1
fi

# ── Step 2: Create ~/sd-cover directory ─────────────────────────────────────
echo ""
echo "Step 2: Create $SD_DIR"
if [[ -d "$SD_DIR" ]]; then
  echo "  ↷ $SD_DIR exists."
else
  mkdir -p "$MODELS_DIR"
  echo "  ✓ Created $SD_DIR and $MODELS_DIR."
fi

# ── Step 3: Create isolated venv ────────────────────────────────────────────
echo ""
echo "Step 3: Python $PY_VERSION venv at $VENV_DIR"
if [[ -d "$VENV_DIR" ]]; then
  echo "  ↷ $VENV_DIR exists."
else
  if [[ "$USE_SYSTEM_TORCH" == "true" ]]; then
    uv venv "$VENV_DIR" --python "$PY_VERSION" --system-site-packages
    echo "  ✓ Created with --system-site-packages (system torch enabled)."
  else
    uv venv "$VENV_DIR" --python "$PY_VERSION"
    echo "  ✓ Created isolated venv."
  fi
fi

PYTHON="$VENV_DIR/bin/python"
PIP="uv pip install --python $PYTHON"

# ── Step 4a: Install cuSPARSELt (Jetson only, torch prerequisite) ──────────
echo ""
echo "Step 4a: Install cuSPARSELt (torch prerequisite)"

if [[ "$USE_SYSTEM_TORCH" == "true" ]]; then
  echo "  ↷ Skipping (--system-torch)."
elif [[ "$arch" != "aarch64" ]]; then
  echo "  ↷ Skipping (not aarch64)."
elif [[ "$SBSA_TORCH" == "true" ]]; then
  echo "  ↷ Skipping (CUDA $CUDA_MAJOR: upstream wheels bundle their CUDA libraries)."
else
  CURRENT_CUSPARSELT=$(dpkg -s libcusparselt0 2>/dev/null | grep "^Version:" | awk '{print $2}' || echo "")
  if [[ "$CURRENT_CUSPARSELT" == "0.7"* ]]; then
    echo "  ↷ cuSPARSELt $CURRENT_CUSPARSELT already installed."
  else
    echo "  Installing cuSPARSELt 0.7.0 tegra package..."
    TMPDIR=$(mktemp -d)
    wget -c -q \
      "https://developer.download.nvidia.com/compute/redist/npott/spconv2/cusparselt/libcusparselt0-tegra_0.7.0.13-1_arm64.deb" \
      -O "$TMPDIR/libcusparselt0-tegra_0.7.0.13-1_arm64.deb"
    sudo dpkg -i "$TMPDIR/libcusparselt0-tegra_0.7.0.13-1_arm64.deb"
    rm -rf "$TMPDIR"
    echo "  ✓ cuSPARSELt installed."
  fi
fi

# ── Step 4b: Install torch ─────────────────────────────────────────────────
echo ""
echo "Step 4b: Install PyTorch"

if [[ "$USE_SYSTEM_TORCH" == "true" ]]; then
  echo "  ↷ Skipping torch install (--system-torch: using system-site-packages)."
  echo "    Make sure system torch is importable: python -c 'import torch; print(torch.cuda.is_available())'"
else
  CURRENT_TORCH=$($PYTHON -c "import torch; print(torch.__version__)" 2>/dev/null || echo "")
  TARGET_TORCH="2.5.0a0"
  if [[ "$SBSA_TORCH" == "true" ]]; then
    if [[ "$CURRENT_TORCH" == "$SBSA_TORCH_VERSION"* ]]; then
      echo "  ↷ torch $CURRENT_TORCH already installed."
    else
      echo "  Installing torch $SBSA_TORCH_VERSION (cu132, upstream wheel)..."
      $PIP "torch==$SBSA_TORCH_VERSION" --index-url "$SBSA_TORCH_INDEX"
      echo "  ✓ torch installed."
    fi
  elif [[ "$CURRENT_TORCH" == "$TARGET_TORCH"* ]]; then
    echo "  ↷ torch $CURRENT_TORCH already installed."
  elif [[ "$arch" != "aarch64" && "$CURRENT_TORCH" == "2.5."* ]]; then
    echo "  ↷ torch $CURRENT_TORCH already installed."
  else
    echo "  Installing torch..."
    if [[ "$arch" == "aarch64" ]]; then
      # Jetson: CUDA-enabled torch for JetPack 6.1 / CUDA 12.6
      TORCH_WHL_URL="https://developer.download.nvidia.com/compute/redist/jp/v61/pytorch/torch-2.5.0a0+872d972e41.nv24.08.17622132-cp310-cp310-linux_aarch64.whl"
      TORCH_WHL_NAME="torch-2.5.0a0+872d972e41.nv24.08.17622132-cp310-cp310-linux_aarch64.whl"
      echo "  Downloading NVIDIA wheel..."
      TMPDIR=$(mktemp -d)
      # uv pip install is idempotent for exact wheel — skip if already installed
      if $PYTHON -c "import torch; exit(0 if torch.__version__ == '$TARGET_TORCH' else 1)" 2>/dev/null; then
        echo "  ↷ torch already installed via system. Skipping."
      else
        wget -c -q "$TORCH_WHL_URL" -O "$TMPDIR/$TORCH_WHL_NAME"
        UV_SKIP_WHEEL_FILENAME_CHECK=1 $PIP --no-cache "$TMPDIR/$TORCH_WHL_NAME"
      fi
      rm -rf "$TMPDIR"
    else
      # Dev machine: standard PyPI + CUDA 12.x wheels (uv pip install is idempotent)
      $PIP torch==2.5.1 --index-url "https://download.pytorch.org/whl/cu126"
    fi
    echo "  ✓ torch installed."
  fi
fi

# ── Step 4c: Build torchvision from source (Jetson only) ────────────────────
echo ""
echo "Step 4c: torchvision"

if [[ "$USE_SYSTEM_TORCH" == "true" ]]; then
  echo "  ↷ Skipping (--system-torch)."
elif [[ "$arch" != "aarch64" ]]; then
  echo "  Installing torchvision from PyPI (x86)..."
  $PIP "torchvision==0.20.1" --index-url "https://download.pytorch.org/whl/cu126"
elif [[ "$SBSA_TORCH" == "true" ]]; then
  TV_IMPORT=$($PYTHON -c "import torchvision; print(torchvision.__version__)" 2>/dev/null || echo "")
  if [[ "$TV_IMPORT" == "$SBSA_TORCHVISION_VERSION"* ]]; then
    echo "  ↷ torchvision $TV_IMPORT already installed."
  else
    echo "  Installing torchvision $SBSA_TORCHVISION_VERSION (cu132, upstream wheel)..."
    $PIP "torch==$SBSA_TORCH_VERSION" "torchvision==$SBSA_TORCHVISION_VERSION" \
      --index-url "$SBSA_TORCH_INDEX"
    echo "  ✓ torchvision installed."
  fi
else
  # PyPI torchvision is x86-only and incompatible with NVIDIA's torch wheel.
  # Must build from source against the exact torch just installed.
  echo "  Checking torchvision..."
  TV_IMPORT=$($PYTHON -c "import torchvision; print(torchvision.__version__)" 2>/dev/null || echo "")
  if [[ "$TV_IMPORT" == "0.20."* ]]; then
    echo "  ↷ torchvision $TV_IMPORT already installed."
  else
    # Check if we already built from source (look for .egg-info)
    EGG_INFO=$(find "$VENV_DIR" -name "torchvision*.egg-info" -type d 2>/dev/null | head -1)
    if [[ -n "$EGG_INFO" ]]; then
      echo "  ↷ torchvision built from source detected. Skipping rebuild."
    else
      echo "  Installing build dependencies..."
      sudo apt-get install -y libjpeg-dev zlib1g-dev libpython3-dev libopenblas-dev \
        libpng-dev libavcodec-dev libavformat-dev libswscale-dev

      echo "  Building torchvision 0.20.0 from source (10–20 min on Jetson)..."
      TV_BUILD_DIR=$(mktemp -d)
      git clone --branch v0.20.0 --depth 1 https://github.com/pytorch/vision.git "$TV_BUILD_DIR/vision"
      cd "$TV_BUILD_DIR/vision"
      BUILD_VERSION=0.20.0 CUDA_HOME=/usr/local/cuda $PYTHON setup.py bdist_wheel
      $PIP dist/*.whl
      cd -
      rm -rf "$TV_BUILD_DIR"
      echo "  ✓ torchvision 0.20.0 built from source."
    fi
  fi
fi

echo "  Installing diffusers + transformers + accelerate + extras..."
$PIP \
  "diffusers==0.31.0" \
  "transformers==4.45.2" \
  "accelerate==1.0.1" \
  "peft" \
  "numpy<2" \
  safetensors \
  pillow
echo "  ✓ Core dependencies installed."

echo "  Installing huggingface_hub..."
$PIP "huggingface_hub[cli]"
echo "  ✓ huggingface_hub installed."

# Record versions
echo "  Recording installed versions to $VERSIONS_FILE..."
$PYTHON -c "
import importlib, sys
pkgs = ['torch', 'torchvision', 'diffusers', 'transformers', 'accelerate', 'safetensors', 'PIL', 'huggingface_hub']
for pkg in pkgs:
    try:
        m = importlib.import_module(pkg)
        v = getattr(m, '__version__', 'unknown')
        print(f'{pkg}=={v}')
    except ImportError:
        print(f'{pkg}==NOT_INSTALLED')
" > "$VERSIONS_FILE"
echo "  ✓ Versions recorded."

# ── Step 5: Download SD 1.5 ─────────────────────────────────────────────────
echo ""
echo "Step 5: Download Stable Diffusion 1.5"
if [[ -f "$SD_MODEL/model_index.json" && -f "$SD_MODEL/unet/diffusion_pytorch_model.safetensors" ]]; then
  echo "  ↷ $SD_MODEL exists with model weights."
else
  # Only the diffusers-format files the pipeline loads: the full repo also
  # carries legacy .ckpt / EMA / fp16 duplicates (~45 GB in total).
  echo "  ✓ Downloading stable-diffusion-v1-5/stable-diffusion-v1-5 (~4.3 GB)..."
  uvx --from huggingface_hub hf download stable-diffusion-v1-5/stable-diffusion-v1-5 \
    --local-dir "$SD_MODEL" \
    --include "model_index.json" --include "scheduler/*" \
    --include "tokenizer/*" --include "feature_extractor/*" \
    --include "text_encoder/config.json" --include "text_encoder/model.safetensors" \
    --include "unet/config.json" --include "unet/diffusion_pytorch_model.safetensors" \
    --include "vae/config.json" --include "vae/diffusion_pytorch_model.safetensors"
  echo "  ✓ Download complete."
fi

# ── Step 6: Download LCM LoRA ───────────────────────────────────────────────
echo ""
echo "Step 6: Download LCM LoRA for SD 1.5"
if [[ -d "$LCM_LORA" ]]; then
  echo "  ↷ $LCM_LORA exists."
else
  echo "  ✓ Downloading latent-consistency/lcm-lora-sdv1-5..."
  uvx --from huggingface_hub hf download latent-consistency/lcm-lora-sdv1-5 --local-dir "$LCM_LORA"
  echo "  ✓ Download complete."
fi

# ── Step 7: Download lineart / coloring-book LoRA candidates ────────────────
echo ""
echo "Step 7: Download lineart LoRA candidates (${#LINEART_LORAS[@]})"
mkdir -p "$LINEART_DIR"
for entry in "${LINEART_LORAS[@]}"; do
  short_name="${entry%%=*}"
  hf_repo="${entry#*=}"
  target_dir="$LINEART_DIR/$short_name"
  if [[ -d "$target_dir" ]] && compgen -G "$target_dir/*.safetensors" > /dev/null; then
    echo "  ↷ $short_name ($hf_repo) exists."
  else
    echo "  ✓ Downloading $short_name from $hf_repo..."
    uvx --from huggingface_hub hf download "$hf_repo" --local-dir "$target_dir"
    echo "  ✓ $short_name download complete."
  fi
done

# ── Step 8: Fuse the LoRAs into the checkpoint the cover worker loads ───────
echo ""
echo "Step 8: Fused checkpoint for the cover worker"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FUSED_MODEL="$MODELS_DIR/sd15-storybot-fused"
if [[ -f "$FUSED_MODEL/model_index.json" ]]; then
  echo "  ↷ $FUSED_MODEL exists."
else
  echo "  Fusing LCM + lineart LoRAs into the base model (CPU, a few minutes)..."
  $PYTHON "$REPO_ROOT/scripts/fuse_sd_loras.py"
  echo "  ✓ Fused checkpoint written."
fi

# ── Verify basic import ─────────────────────────────────────────────────────
echo ""
echo "Verifying imports..."
$PYTHON -c "import torch, diffusers, transformers; print(f'  ✓ torch {torch.__version__}, diffusers {diffusers.__version__}, CUDA: {torch.cuda.is_available()}')"

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════════════════"
echo "✓  SD 1.5 + LCM LoRA setup complete."
echo ""
echo "Venv:    $VENV_DIR"
echo "Models:  $MODELS_DIR"
echo "Versions: $VERSIONS_FILE"
echo ""
first_lora="${LINEART_LORAS[0]%%=*}"
echo "Lineart LoRAs downloaded:"
for entry in "${LINEART_LORAS[@]}"; do
  echo "  - ${entry%%=*}  (${entry#*=})"
done
echo ""
echo "NEXT: Run the benchmark (from storybot repo root, after stopping llama-server):"
echo ""
echo "  $PYTHON scripts/bench_sd.py \\"
echo "    --prompts .paul/phases/15-cover-images/research/prompts.md \\"
echo "    --lineart-lora $first_lora \\"
echo "    --lcm-steps 4 --gen-resolution 640 --output-resolution 696 \\"
echo "    --threshold 128 --output /tmp/bench-sd.jsonl"
echo ""
echo "  Repeat with --lineart-lora <other-short-name> to compare candidates."
echo "══════════════════════════════════════════════════════════════"
