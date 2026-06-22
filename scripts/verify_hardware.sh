#!/bin/bash
# StoryBot Hardware Verification — Phase 08
# Run on Jetson: bash scripts/verify_hardware.sh
# Paste full output back into conversation.

BASE_URL="http://localhost:8000"

echo "======================================"
echo " StoryBot Hardware Verification v1.0"
echo " Date: $(date)"
echo " Host: $(hostname)"
echo "======================================"
echo ""

# INFRA-01: FastAPI responds on port 8000
echo "=== INFRA-01: FastAPI health ==="
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" $BASE_URL/api/system/status)
echo "GET /api/system/status → HTTP $HTTP_CODE (expected: 200)"
if [ "$HTTP_CODE" = "200" ]; then
  echo "RESULT: PASS"
else
  echo "RESULT: FAIL"
fi
echo ""

# INFRA-01 + INFRA-02 + INFRA-05: Full system status (shows all hardware)
echo "=== System status (all hardware services) ==="
curl -s $BASE_URL/api/system/status | python3 -m json.tool
echo ""

# INFRA-03: NFC service status
echo "=== INFRA-03: NFC service status ==="
curl -s $BASE_URL/api/nfc/status | python3 -m json.tool
echo ""

# INFRA-04: LED API command (always mock by design — verifying API responds)
echo "=== INFRA-04: LED API command (set red) ==="
curl -s -X POST $BASE_URL/api/system/led \
  -H "Content-Type: application/json" \
  -d '{"color":"#FF0000"}' | python3 -m json.tool
echo "NOTE: After Phase 34 bring-up, is_mock=false is expected on real hardware (LED-26)"
echo ""

# LED-26: SPI node + permissions (post-reboot smoke)
echo "=== LED-26: SPI node + permissions ==="
if ls /dev/spidev* 2>/dev/null; then
  echo "PASS: spidev node(s) present"
else
  echo "FAIL: no /dev/spidev* node found — SPI1 may not be enabled or reboot required"
fi
getent group spi && echo "PASS: spi group exists" || echo "FAIL: spi group not found"
if sudo -u "$INSTALL_USER" test -w /dev/spidev0.0 2>/dev/null; then
  echo "PASS: service user can write SPI node"
else
  echo "WARN: service user cannot write /dev/spidev0.0 (may be pre-reboot or node differs)"
fi
echo ""

# Turn LED off after test
curl -s -X POST $BASE_URL/api/system/led/off > /dev/null

# INFRA-02: Piper TTS model file check
echo "=== INFRA-02: Piper model file ==="
MODEL="$HOME/.local/share/piper/es_ES-sharvard-medium.onnx"
CONFIG="$HOME/.local/share/piper/es_ES-sharvard-medium.onnx.json"
if [ -f "$MODEL" ]; then
  echo "PASS: Model file found"
  ls -lh "$MODEL"
  if [ -f "$CONFIG" ]; then
    echo "PASS: Config file found"
    ls -lh "$CONFIG"
  else
    echo "WARN: Config file not found at $CONFIG"
  fi
else
  echo "FAIL: Model not found at $MODEL"
  echo "Contents of ~/.local/share/piper/ (if exists):"
  ls -la "$HOME/.local/share/piper/" 2>/dev/null || echo "(directory not found)"
fi
echo ""

# INFRA-05: ALSA audio devices
echo "=== INFRA-05: ALSA audio devices ==="
aplay -l 2>&1 | head -20
echo ""

# System info
echo "=== System info ==="
echo "Arch: $(uname -m)"
echo "Kernel: $(uname -r)"
uname -a
echo ""

echo "======================================"
echo " Script complete."
echo " Next steps for manual tests:"
echo "  1. INFRA-03 (NFC tap): Open http://localhost/admin"
echo "     → Tap a physical NFC card on the reader"
echo "     → Confirm a UID appears in the admin panel"
echo "  2. INFRA-05 (Audio): Click a story in the kiosk"
echo "     at http://localhost/"
echo "     → Confirm audio plays through the speakers"
echo " Paste this full output + your Y/N for both manual tests."
echo "======================================"
