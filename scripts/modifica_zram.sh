#!/usr/bin/env bash
set -euo pipefail

NUM_DEVICES=6
SIZE_MB=1500
ALGORITHM=lzo-rle
PRIORITY=10

echo "=== Zram Setup for Jetson ==="

# 1. Turn off any existing zram swap (ignore errors)
echo "Stopping existing zram swap..."
for dev in /dev/zram*; do
    [ -e "$dev" ] && sudo swapoff "$dev" 2>/dev/null || true
done

# 2. Unload the module (clears all devices)
echo "Unloading zram module..."
sudo modprobe -r zram 2>/dev/null || true

# 3. Reload with the desired number of devices
echo "Loading zram module with $NUM_DEVICES devices..."
sudo modprobe zram num_devices=$NUM_DEVICES

# 4. Wait for devices to appear
sleep 1
if [ ! -e /dev/zram0 ]; then
    echo "ERROR: /dev/zram0 not found after modprobe. Aborting."
    exit 1
fi

# 5. Configure each device
for i in $(seq 0 $((NUM_DEVICES - 1))); do
    dev="/dev/zram${i}"
    echo "  Configuring $dev: ${SIZE_MB}M, algorithm=$ALGORITHM"
    sudo zramctl "$dev" --algorithm "$ALGORITHM" --size "${SIZE_MB}M"
    sudo mkswap "$dev" >/dev/null
    sudo swapon "$dev" -p "$PRIORITY"
done

echo ""
echo "=== Done. Current state: ==="
echo ""
zramctl
echo ""
free -h
