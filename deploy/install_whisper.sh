#!/usr/bin/env bash
# install_whisper.sh — Reproducible setup of whisper.cpp for audio transcription
# Target: Jetson Orin Nano Super 8GB, aarch64 (also fine on an x86 dev machine)
#
# Builds whisper.cpp CPU-only at ~/whisper.cpp (the app runs whisper-cli with
# --no-gpu, so CUDA flags would have no effect), downloads the multilingual
# "small" model and points content/config.json at both.
#
# Usage:
#   bash deploy/install_whisper.sh        (as the user that runs storybot)
# deploy/install.sh calls it as the install user. Needs no root; ffmpeg, which
# the app uses to convert uploads to 16 kHz mono WAV, is installed by install.sh.
# Idempotent: every step is skipped when its result is already in place.
set -euo pipefail

WHISPER_DIR="$HOME/whisper.cpp"
WHISPER_BIN="$WHISPER_DIR/build/bin/whisper-cli"
WHISPER_MODEL_NAME="small"
WHISPER_MODEL="$WHISPER_DIR/models/ggml-$WHISPER_MODEL_NAME.bin"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_JSON="$REPO_ROOT/content/config.json"

# ── Step 1: Source ──────────────────────────────────────────────────────────
echo ""
echo "Step 1: whisper.cpp source"
if [[ -d "$WHISPER_DIR/.git" ]]; then
  echo "  ↷ $WHISPER_DIR exists."
else
  git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git "$WHISPER_DIR"
  echo "  ✓ Cloned whisper.cpp."
fi

# ── Step 2: Build (CPU only) ────────────────────────────────────────────────
echo ""
echo "Step 2: Build whisper-cli"
if [[ -x "$WHISPER_BIN" ]]; then
  echo "  ↷ $WHISPER_BIN exists."
else
  cmake -B "$WHISPER_DIR/build" -S "$WHISPER_DIR" -DCMAKE_BUILD_TYPE=Release
  cmake --build "$WHISPER_DIR/build" --config Release -j"$(nproc)"
  echo "  ✓ Build complete."
fi

# ── Step 3: Model ───────────────────────────────────────────────────────────
echo ""
echo "Step 3: Download the '$WHISPER_MODEL_NAME' model (~466 MB)"
MODEL_SIZE=$(stat -c%s "$WHISPER_MODEL" 2>/dev/null || echo 0)
if [[ "$MODEL_SIZE" -gt 400000000 ]]; then
  echo "  ↷ $WHISPER_MODEL exists ($((MODEL_SIZE / 1024 / 1024)) MB)."
else
  # A partial file from an interrupted download would be mistaken for the model.
  rm -f "$WHISPER_MODEL"
  bash "$WHISPER_DIR/models/download-ggml-model.sh" "$WHISPER_MODEL_NAME"
  echo "  ✓ Model downloaded."
fi

# ── Step 4: Point the app at this build ─────────────────────────────────────
# The shipped config.json may carry another machine's absolute paths. Rewrite
# the two whisper keys only when the configured ones do not resolve here.
echo ""
echo "Step 4: content/config.json"
python3 - "$CONFIG_JSON" "$WHISPER_BIN" "$WHISPER_MODEL" "$REPO_ROOT" <<'PY'
import json
import shutil
import sys
from pathlib import Path

config_path, whisper_bin, whisper_model, repo_root = sys.argv[1:5]
path = Path(config_path)
data = json.loads(path.read_text()) if path.exists() else {}

current_bin = data.get("whisper_bin", "whisper-cli")
current_model = Path(data.get("whisper_model", "models/whisper/ggml-small.bin"))
if not current_model.is_absolute():
    current_model = Path(repo_root) / current_model

if shutil.which(current_bin) and current_model.exists():
    print("  ↷ Configured whisper paths already resolve.")
else:
    data["whisper_bin"] = whisper_bin
    data["whisper_model"] = whisper_model
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"  ✓ whisper_bin / whisper_model set in {path}.")
PY

# ── Verify ──────────────────────────────────────────────────────────────────
echo ""
if command -v ffmpeg &>/dev/null; then
  echo "  ✓ ffmpeg found."
else
  echo "  ⚠  ffmpeg not found — transcription stays off until: sudo apt install ffmpeg"
fi
"$WHISPER_BIN" --help >/dev/null 2>&1 && echo "  ✓ whisper-cli runs."

echo ""
echo "✓  whisper.cpp setup complete. Restart storybot to pick up the config."
