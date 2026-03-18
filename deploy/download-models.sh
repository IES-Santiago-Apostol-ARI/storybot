#!/bin/bash
#
# Download Piper TTS models for StoryBot
#
# This script downloads the Spanish voice model for text-to-speech.
# The model files are approximately 77MB total.
#
set -e

MODELS_DIR="${1:-${HOME}/.local/share/piper}"
mkdir -p "$MODELS_DIR"

# Spanish voice (es_ES-sharvard-medium)
VOICE="es_ES-sharvard-medium"
BASE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/sharvard/medium"

echo "================================================"
echo "StoryBot Piper TTS Model Download"
echo "================================================"
echo "Voice: $VOICE"
echo "Target directory: $MODELS_DIR"
echo ""

# Check if model already exists
if [ -f "$MODELS_DIR/$VOICE.onnx" ] && [ -f "$MODELS_DIR/$VOICE.onnx.json" ]; then
    echo "Model files already exist:"
    ls -lh "$MODELS_DIR/$VOICE".*
    echo "Skipping download. Pass a different directory or remove files to re-download."
    exit 0
fi

echo "Downloading model files from HuggingFace..."
echo ""

# Download ONNX model
echo "1. Downloading $VOICE.onnx (~73MB)..."
curl -L -o "$MODELS_DIR/$VOICE.onnx" "$BASE_URL/$VOICE.onnx"

# Download model config
echo "2. Downloading $VOICE.onnx.json (~4KB)..."
curl -L -o "$MODELS_DIR/$VOICE.onnx.json" "$BASE_URL/$VOICE.onnx.json"

echo ""
echo "================================================"
echo "Download complete!"
echo "================================================"
echo ""
echo "Files downloaded:"
ls -lh "$MODELS_DIR/$VOICE".*
echo ""
echo "Model location: $MODELS_DIR"
echo "Voice name: $VOICE"
echo ""
echo "To use this model in StoryBot:"
echo "  1. Ensure the model path is configured in app/config.py"
echo "  2. The TTS service will load it at startup"
echo ""
