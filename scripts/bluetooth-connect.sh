#!/bin/bash

DEVICE="00:42:79:E9:90:46"

# Wait for Bluetooth service
sleep 5

# Ensure bluetooth is powered
bluetoothctl power on

# Try connecting (retry loop)
for i in {1..10}; do
    bluetoothctl connect $DEVICE && break
    sleep 3
done

# Wait for PipeWire to register device
sleep 5

# Set A2DP profile (ignore errors if already set)
pactl set-card-profile bluez_card.${DEVICE//:/_} a2dp-sink 2>/dev/null

# Set as default sink
SINK="bluez_output.${DEVICE//:/_}.a2dp-sink"
pactl set-default-sink $SINK 2>/dev/null
