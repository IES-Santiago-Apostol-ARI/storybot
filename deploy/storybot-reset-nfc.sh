#!/bin/bash
# Reset the ACR122U NFC reader to fix LIBUSB_ERROR_TIMEOUT after reboot.
# Runs as a oneshot systemd service before pcscd starts.
#
# The reader can get stuck answering each CCID command only when the next one
# arrives (replies lag one behind), which libccid reports as a timeout. The hub
# port power cycle does not clear this (the hub doesn't really cut VBUS), but a
# USB bus reset of the device does.

UHUBCTL_OUT=$(uhubctl 2>/dev/null)

PORT_LINE=$(echo "$UHUBCTL_OUT" | grep "072f:2200")
if [ -n "$PORT_LINE" ]; then
    PORT=$(echo "$PORT_LINE" | grep -oP "Port \K[0-9]+")
    HUB=$(echo "$UHUBCTL_OUT" | grep -B20 "072f:2200" | grep "^Current status for hub" | tail -1 | grep -oP "hub \K[^ ]+")

    echo "Power cycling ACR122U: hub=$HUB port=$PORT"
    uhubctl -l "$HUB" -p "$PORT" -a off
    sleep 2
    uhubctl -l "$HUB" -p "$PORT" -a on
else
    echo "ACR122U not found via uhubctl, skipping power cycle"
fi

# Wait for (re-)enumeration (the udev rule then disables autosuspend)
for _ in $(seq 1 20); do
    lsusb -d 072f:2200 >/dev/null 2>&1 && break
    sleep 0.5
done
if ! lsusb -d 072f:2200 >/dev/null 2>&1; then
    echo "ACR122U not present, skipping USB reset"
    exit 0
fi

echo "USB-resetting ACR122U"
usbreset 072f:2200 || echo "usbreset failed (continuing)"
sleep 2
echo "ACR122U reset complete"
