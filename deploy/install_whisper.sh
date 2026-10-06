#!/usr/bin/env bash
# install_whisper.sh — Reproducible setup of whisper.cpp for audio transcription
# Target: Jetson Orin Nano Super 8GB, aarch64 (also fine on an x86 dev machine)
#
# Builds whisper.cpp CPU-only at ~/whisper.cpp (the app runs whisper-cli with
# --no-gpu, so CUDA flags would have no effect), downloads the multilingual
# "small" model. Nothing is written to content/config.json: the app finds this
# standard location by itself (app/services/transcriber.py), so the install
# survives an OTA update's `git reset --hard`.
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

# ── Verify ──────────────────────────────────────────────────────────────────
echo ""
if command -v ffmpeg &>/dev/null; then
  echo "  ✓ ffmpeg found."
else
  echo "  ⚠  ffmpeg not found — transcription stays off until: sudo apt install ffmpeg"
fi
"$WHISPER_BIN" --help >/dev/null 2>&1 && echo "  ✓ whisper-cli runs."

echo ""
echo "✓  whisper.cpp setup complete."
