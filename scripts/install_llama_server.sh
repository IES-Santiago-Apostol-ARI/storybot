#!/usr/bin/env bash
# install_llama_server.sh — Reproducible Jetson setup for Qwen 3.5 4B + llama.cpp
# Target: Jetson Orin Nano Super 8GB, JetPack 6.2.1, aarch64
set -euo pipefail

LLAMA_DIR="$HOME/llama.cpp"
MODEL_DIR="$LLAMA_DIR/models/Qwen3.5-4B-GGUF"
MODEL_FILE="Qwen3.5-4B-Q4_K_M.gguf"
MODEL_PATH="$MODEL_DIR/$MODEL_FILE"
SWAPFILE="/var/swapfile"
REBUILD="${REBUILD:-false}"

if [[ "${1:-}" == "--rebuild" ]]; then
  REBUILD=true
fi

arch=$(uname -m)
if [[ "$arch" != "aarch64" ]]; then
  echo "⚠  Not running on aarch64 (detected: $arch). Some steps will be skipped."
  echo "   This is fine for a dev-machine dry-run."
fi

# ── Step 1: CUDA paths ──────────────────────────────────────────────────────
echo ""
echo "Step 1: CUDA environment paths"
CUDA_BIN="/usr/local/cuda/bin"
CUDA_LIB="/usr/local/cuda/lib64"

for dir in "$CUDA_BIN" "$CUDA_LIB"; do
  case ":$PATH:" in
    *":$dir:"*) echo "  ✓ $dir already in PATH" ;;
    *)
      export PATH="$PATH:$dir"
      export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}:$dir"
      if ! grep -q "$dir" ~/.bashrc 2>/dev/null; then
        echo "export PATH=\"\$PATH:$dir\"" >> ~/.bashrc
        echo "export LD_LIBRARY_PATH=\"\${LD_LIBRARY_PATH:-}:$dir\"" >> ~/.bashrc
        echo "  ✓ Appended $dir to ~/.bashrc"
      else
        echo "  ↷ $dir already in ~/.bashrc"
      fi
      ;;
  esac
done

# ── Step 2: Swap (before build — compilation needs the headroom) ────────────
echo ""
echo "Step 2: 8 GB swapfile at $SWAPFILE"
if swapon --show | grep -q "$SWAPFILE"; then
  echo "  ↷ $SWAPFILE already active."
else
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "  ⚠  Not root — cannot create swapfile. Run with sudo or set up manually:"
    echo "     sudo fallocate -l 8G $SWAPFILE"
    echo "     sudo chmod 600 $SWAPFILE"
    echo "     sudo mkswap $SWAPFILE"
    echo "     sudo swapon $SWAPFILE"
    echo "     echo '$SWAPFILE none swap sw 0 0' | sudo tee -a /etc/fstab"
  else
    if [[ ! -f "$SWAPFILE" ]]; then
      fallocate -l 8G "$SWAPFILE"
      chmod 600 "$SWAPFILE"
      mkswap "$SWAPFILE"
    fi
    swapon "$SWAPFILE"
    if ! grep -q "$SWAPFILE" /etc/fstab; then
      echo "$SWAPFILE none swap sw 0 0" >> /etc/fstab
    fi
    echo "  ✓ Swapfile created and activated."
  fi
fi

# ── Step 3: Power mode ──────────────────────────────────────────────────────
echo ""
echo "Step 3: Jetson power mode"
if command -v nvpmodel &>/dev/null; then
  sudo nvpmodel -m 0
  sudo jetson_clocks 2>/dev/null || true
  echo "  ✓ nvpmodel MAXN + jetson_clocks applied."
else
  echo "  ↷ nvpmodel not found (not a Jetson). Skipping."
fi

# ── Step 4: Clone / update llama.cpp ─────────────────────────────────────────
echo ""
echo "Step 4: llama.cpp source"
if [[ -d "$LLAMA_DIR/.git" ]]; then
  echo "  ↷ $LLAMA_DIR exists, pulling latest..."
  git -C "$LLAMA_DIR" pull --ff-only || true
else
  echo "  ✓ Cloning llama.cpp..."
  git clone https://github.com/ggml-org/llama.cpp.git "$LLAMA_DIR"
fi

# ── Step 5: Build with CUDA ─────────────────────────────────────────────────
echo ""
echo "Step 5: Build llama.cpp with CUDA"
SERVER_BIN="$LLAMA_DIR/build/bin/llama-server"
NEED_BUILD=true

if [[ "$REBUILD" == "false" && -x "$SERVER_BIN" ]]; then
  NEWEST_SRC=$(find "$LLAMA_DIR/src" "$LLAMA_DIR/ggml" "$LLAMA_DIR/common" -newer "$SERVER_BIN" -type f 2>/dev/null | head -1)
  if [[ -z "$NEWEST_SRC" ]]; then
    echo "  ↷ $SERVER_BIN exists and is up-to-date. Skipping build."
    NEED_BUILD=false
  else
    echo "  ⚠  Source newer than binary — rebuilding."
  fi
fi

if [[ "$NEED_BUILD" == "true" ]]; then
  echo "  ✓ Building (cmake + make)..."
 # cmake -B "$LLAMA_DIR/build" -S "$LLAMA_DIR" -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release
  cmake -B "$LLAMA_DIR/build" -S "$LLAMA_DIR" -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release -DLLAMA_BUILD_TESTS=OFF  -DLLAMA_BUILD_EXAMPLES=OFF -DCMAKE_CUDA_ARCHITECTURES=87 -DCMAKE_CUDA_STANDARD=17
   #  cmake --build "$LLAMA_DIR/build" --parallel
  cmake --build "$LLAMA_DIR/build" -j4
  echo "  ✓ Build complete."
fi

# ── Step 6: Download model via uvx (isolated, no global pip needed) ─────────
echo ""
echo "Step 6: Download Qwen 3.5 4B Q4_K_M GGUF"
mkdir -p "$MODEL_DIR"
if [[ -f "$MODEL_PATH" ]]; then
  SIZE=$(stat -c%s "$MODEL_PATH" 2>/dev/null || stat -f%z "$MODEL_PATH" 2>/dev/null || echo 0)
  if [[ "$SIZE" -gt 2000000000 ]]; then
    echo "  ↷ $MODEL_PATH exists ($(($SIZE / 1024 / 1024)) MB). Skipping download."
  else
    echo "  ⚠  File exists but seems too small ($(($SIZE / 1024 / 1024)) MB). Re-downloading..."
    uvx --from huggingface_hub hf download unsloth/Qwen3.5-4B-GGUF "$MODEL_FILE" --local-dir "$MODEL_DIR"
    echo "  ✓ Download complete."
  fi
else
  echo "  ✓ Downloading ~2.5 GB model..."
  uvx --from huggingface_hub hf download unsloth/Qwen3.5-4B-GGUF "$MODEL_FILE" --local-dir "$MODEL_DIR"
  echo "  ✓ Download complete."
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════════════════"
echo "✓  Setup complete."
echo ""
echo "NEXT: Launch llama-server and run the benchmark."
echo ""
echo "  # Start server (tune flags as needed — see Task 2 in PLAN):"
echo "  $LLAMA_DIR/build/bin/llama-server \\"
echo "    -m $MODEL_PATH \\"
echo "    --alias qwen35-4b-local \\"
echo "    -t 6 -c 8192 --n-gpu-layers 28 \\"
echo "    --batch-size 256 --ubatch-size 64 \\"
echo "    --no-mmap --mlock \\"
echo "    --host 127.0.0.1 --port 8080"
echo ""
echo "~/llama.cpp/build/bin/llama-server -m ~/llama.cpp/models/Qwen3.5-4B-GGUF/Qwen3.5-4B-Q4_K_M.gguf --alias qwen35-4b-local  -t 6 -c 8192 --n-gpu-layers 28 --batch-size 256 --ubatch-size 64 --no-mmap --mlock --reasoning off --reasoning-format none  --host 127.0.0.1 --port 8080"
echo "~/llama.cpp/build/bin/llama-server -m ~/llama.cpp/models/Qwen3.5-4B-GGUF/Qwen3.5-4B-Q4_K_M.gguf \\"
echo " --alias qwen35-4b-local -np 1 -t 6 -c 8192 --n-gpu-layers 32 --cache-ram 512  --batch-size 256 \\"
echo " --ubatch-size 64 --no-mmap --mlock --reasoning off --reasoning-format none  --host 127.0.0.1 --port 8080"
echo ""
echo "  # Run benchmark (from storybot repo root):"
echo "  uv run python scripts/bench_llm.py --prompts .paul/phases/13-llm-story-generation/research/prompts.md"
echo "══════════════════════════════════════════════════════════════"
