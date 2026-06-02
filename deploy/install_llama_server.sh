#!/usr/bin/env bash
# install_llama_server.sh — Reproducible Jetson setup for Qwen 3.5 4B + llama.cpp
# Target: Jetson Orin Nano Super 8GB, JetPack 6.2.1, aarch64
#
# Usage:
#   bash scripts/install_llama_server.sh          (as the target user)
#   sudo bash scripts/install_llama_server.sh     (as root — TARGET_USER must be set)
#
set -euo pipefail

# Determine the target user for home directory paths.
# When run with sudo, $SUDO_USER is the original user; $HOME is /root.
# When run without sudo, $USER/$HOME is correct.
if [[ -n "${SUDO_USER:-}" ]]; then
  TARGET_USER="$SUDO_USER"
elif [[ -n "${TARGET_USER:-}" ]]; then
  TARGET_USER="$TARGET_USER"
else
  TARGET_USER="$USER"
fi
LLAMA_DIR="/home/$TARGET_USER/llama.cpp"
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
      USER_BASHRC="/home/$TARGET_USER/.bashrc"
      if ! grep -q "$dir" "$USER_BASHRC" 2>/dev/null; then
        echo "export PATH=\"\$PATH:$dir\"" >> "$USER_BASHRC"
        echo "export LD_LIBRARY_PATH=\"\${LD_LIBRARY_PATH:-}:$dir\"" >> "$USER_BASHRC"
        echo "  ✓ Appended $dir to $USER_BASHRC"
      else
        echo "  ↷ $dir already in $USER_BASHRC"
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
    if ! swapon --show | grep -q "$SWAPFILE"; then
      swapon "$SWAPFILE"
    fi
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
CLONE_NEW=false
if [[ -d "$LLAMA_DIR/.git" ]]; then
  echo "  ↷ $LLAMA_DIR exists. Skipping pull (run 'git pull' manually if needed)."
else
  echo "  ✓ Cloning llama.cpp..."
  git clone https://github.com/ggml-org/llama.cpp.git "$LLAMA_DIR"
  CLONE_NEW=true
fi

# ── Step 5: Build with CUDA ─────────────────────────────────────────────────
echo ""
echo "Step 5: Build llama.cpp with CUDA"
SERVER_BIN="$LLAMA_DIR/build/bin/llama-server"
NEED_BUILD=true

if [[ "$REBUILD" == "true" ]]; then
  echo "  ⚠  Forced rebuild (--rebuild passed)."
  NEED_BUILD=true
elif [[ -x "$SERVER_BIN" ]]; then
  echo "  ↷ $SERVER_BIN exists. Skipping build."
  NEED_BUILD=false
elif [[ "$CLONE_NEW" == "true" ]]; then
  echo "  ↷ Fresh clone detected — building."
  NEED_BUILD=true
else
  echo "  ⚠  $SERVER_BIN not found — building."
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

# ── Step 7: Install systemd unit ──────────────────────────────────────────────
echo ""
echo "Step 7: Install systemd unit"
SERVICE_FILE="$LLAMA_DIR/../deploy/llama-server.service"
if [[ ! -f "$SERVICE_FILE" ]]; then
  # Try the deploy directory relative to storybot repo
  STORYBOT_DIR="/home/$TARGET_USER/storybot"
  SERVICE_FILE="$STORYBOT_DIR/deploy/llama-server.service"
fi
if [[ ! -f "$SERVICE_FILE" ]]; then
  # Try current directory
  SERVICE_FILE="$(pwd)/deploy/llama-server.service"
fi
if [[ -f "$SERVICE_FILE" ]]; then
  echo "  Installing from $SERVICE_FILE..."
  # Substitute the template placeholders for the target user / home directory.
  sudo sed -e "s|__INSTALL_USER__|$TARGET_USER|g" \
           -e "s|__INSTALL_HOME__|/home/$TARGET_USER|g" \
           "$SERVICE_FILE" | sudo tee /etc/systemd/system/llama-server.service >/dev/null
else
  echo "  ⚠  Service file not found — copy manually:"
  echo "     sudo cp deploy/llama-server.service /etc/systemd/system/"
fi
sudo systemctl daemon-reload
sudo systemctl enable llama-server
sudo systemctl start llama-server
if sudo systemctl is-active --quiet llama-server 2>/dev/null; then
  echo "  ✓ llama-server service started."
else
  echo "  ⚠  llama-server failed to start. Check with: sudo systemctl status llama-server"
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════════════════"
echo "✓  Setup complete."
echo ""
echo "NEXT: Verify and run the benchmark."
echo ""
echo "  # Verify llama-server is responding:"
echo "  curl -s http://127.0.0.1:8080/v1/models | python3 -m json.tool"
echo ""
echo "  # Start server manually (tune flags as needed — see Task 2 in PLAN):"
echo "  $LLAMA_DIR/build/bin/llama-server \\"
echo "    -m $MODEL_PATH \\"
echo "    --alias qwen35-4b-local \\"
echo "    -t 6 -c 8192 --n-gpu-layers 32 \\"
echo "    --batch-size 256 --ubatch-size 64 \\"
echo "    --no-mmap --mlock \\"
echo "    --host 127.0.0.1 --port 8080"
echo ""
echo "  # Run benchmark (from storybot repo root):"
echo "  uv run python scripts/bench_llm.py --prompts .paul/phases/13-llm-story-generation/research/prompts.md"
echo "══════════════════════════════════════════════════════════════"
