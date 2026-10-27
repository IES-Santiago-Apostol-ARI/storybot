#!/bin/bash
# Power-cycle the ACR122U USB port to fix LIBUSB_ERROR_TIMEOUT after reboot.
# Runs as a oneshot systemd service before pcscd starts.

UHUBCTL_OUT=$(uhubctl 2>/dev/null)

PORT_LINE=$(echo "$UHUBCTL_OUT" | grep "072f:2200")
if [ -z "$PORT_LINE" ]; then
    echo "ACR122U not found via uhubctl, skipping reset"
    exit 0
fi

PORT=$(echo "$PORT_LINE" | grep -oP "Port \K[0-9]+")
HUB=$(echo "$UHUBCTL_OUT" | grep -B20 "072f:2200" | grep "^Current status for hub" | tail -1 | grep -oP "hub \K[^ ]+")

echo "Power cycling ACR122U: hub=$HUB port=$PORT"
uhubctl -l "$HUB" -p "$PORT" -a off
sleep 2
uhubctl -l "$HUB" -p "$PORT" -a on
sleep 3
echo "ACR122U power cycle complete"
