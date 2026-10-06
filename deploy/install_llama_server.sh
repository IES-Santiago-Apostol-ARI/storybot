#!/usr/bin/env bash
# install_llama_server.sh — Reproducible Jetson setup for Qwen 3.5 4B + llama.cpp
# Target: Jetson Orin Nano Super 8GB, JetPack 6.2.1 / 7.2, aarch64
#
# Usage:
#   sudo bash deploy/install_llama_server.sh      (root: everything, incl. swap + unit)
#   bash deploy/install_llama_server.sh           (target user: source, build and model
#                                                  only — swap and the unit need root)
# deploy/install.sh calls it as root with TARGET_USER set to the install user.
# Idempotent: every step is skipped when its result is already in place.
#
set -euo pipefail

# Determine the target user for home directory paths. An explicit TARGET_USER
# wins: under install.sh, $SUDO_USER is whoever typed sudo, which is not
# necessarily the service account. Otherwise fall back to $SUDO_USER, then $USER.
if [[ -n "${TARGET_USER:-}" ]]; then
  TARGET_USER="$TARGET_USER"
elif [[ -n "${SUDO_USER:-}" ]]; then
  TARGET_USER="$SUDO_USER"
else
  TARGET_USER="$USER"
fi
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
IS_ROOT=false
if [[ "$(id -u)" -eq 0 ]]; then IS_ROOT=true; fi

# Run a command as the target user, so nothing under their home ends up owned
# by root when this script runs as root.
as_user() {
  if [[ "$IS_ROOT" == "true" ]]; then
    sudo -u "$TARGET_USER" -H env \
      PATH="/home/$TARGET_USER/.local/bin:/usr/local/cuda/bin:/usr/local/bin:/usr/bin:/bin" \
      LD_LIBRARY_PATH="/usr/local/cuda/lib64" "$@"
  else
    "$@"
  fi
}
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
# Reported, not changed: mode IDs differ per board (on the Orin Nano Super
# ID 0 is 15W, not MAXN), and deploy/install.sh owns the power mode.
if command -v nvpmodel &>/dev/null; then
  echo "  ↷ $(nvpmodel -q 2>/dev/null | head -1 || echo 'power mode unknown') (left unchanged)."
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
  as_user git clone https://github.com/ggml-org/llama.cpp.git "$LLAMA_DIR"
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
  as_user cmake -B "$LLAMA_DIR/build" -S "$LLAMA_DIR" -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release -DLLAMA_BUILD_TESTS=OFF  -DLLAMA_BUILD_EXAMPLES=OFF -DCMAKE_CUDA_ARCHITECTURES=87 -DCMAKE_CUDA_STANDARD=17
   #  cmake --build "$LLAMA_DIR/build" --parallel
  as_user cmake --build "$LLAMA_DIR/build" -j4
  echo "  ✓ Build complete."
fi

# ── Step 6: Download model via uvx (isolated, no global pip needed) ─────────
echo ""
echo "Step 6: Download Qwen 3.5 4B Q4_K_M GGUF"
as_user mkdir -p "$MODEL_DIR"
if [[ -f "$MODEL_PATH" ]]; then
  SIZE=$(stat -c%s "$MODEL_PATH" 2>/dev/null || stat -f%z "$MODEL_PATH" 2>/dev/null || echo 0)
  if [[ "$SIZE" -gt 2000000000 ]]; then
    echo "  ↷ $MODEL_PATH exists ($(($SIZE / 1024 / 1024)) MB). Skipping download."
  else
    echo "  ⚠  File exists but seems too small ($(($SIZE / 1024 / 1024)) MB). Re-downloading..."
    as_user uvx --from huggingface_hub hf download unsloth/Qwen3.5-4B-GGUF "$MODEL_FILE" --local-dir "$MODEL_DIR"
    echo "  ✓ Download complete."
  fi
else
  echo "  ✓ Downloading ~2.5 GB model..."
  as_user uvx --from huggingface_hub hf download unsloth/Qwen3.5-4B-GGUF "$MODEL_FILE" --local-dir "$MODEL_DIR"
  echo "  ✓ Download complete."
fi

# ── Step 7: Install systemd unit ──────────────────────────────────────────────
echo ""
echo "Step 7: Install systemd unit"
SERVICE_FILE="$SCRIPT_DIR/llama-server.service"
if [[ "$IS_ROOT" != "true" ]]; then
  echo "  ⚠  Not root — unit not installed. Finish with:"
  echo "     sudo TARGET_USER=$TARGET_USER bash $SCRIPT_DIR/install_llama_server.sh"
elif [[ ! -f "$SERVICE_FILE" ]]; then
  echo "  ⚠  $SERVICE_FILE not found — unit not installed."
else
  # Substitute the template placeholders for the target user / home directory.
  UNIT_TMP="$(mktemp)"
  sed -e "s|__INSTALL_USER__|$TARGET_USER|g" \
      -e "s|__INSTALL_HOME__|/home/$TARGET_USER|g" \
      "$SERVICE_FILE" > "$UNIT_TMP"
  if cmp -s "$UNIT_TMP" /etc/systemd/system/llama-server.service 2>/dev/null; then
    echo "  ↷ Unit already installed and up to date."
  else
    install -m 0644 "$UNIT_TMP" /etc/systemd/system/llama-server.service
    systemctl daemon-reload
    echo "  ✓ Unit installed."
  fi
  rm -f "$UNIT_TMP"
  systemctl enable llama-server
  if systemctl is-active --quiet llama-server; then
    echo "  ↷ llama-server already running."
  else
    systemctl start llama-server || true
    if systemctl is-active --quiet llama-server; then
      echo "  ✓ llama-server service started."
    else
      echo "  ⚠  llama-server failed to start. Check with: sudo systemctl status llama-server"
    fi
  fi
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
echo "    --no-mmap \\"
echo "    --host 127.0.0.1 --port 8080"
echo ""
echo "  # Run benchmark (from storybot repo root):"
echo "  uv run python scripts/bench_llm.py --prompts .paul/phases/13-llm-story-generation/research/prompts.md"
echo "══════════════════════════════════════════════════════════════"
