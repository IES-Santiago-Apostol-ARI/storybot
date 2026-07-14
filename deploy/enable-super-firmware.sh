#!/bin/bash
#
# enable-super-firmware.sh — one-time QSPI firmware migration to the "Super"
# profile for a Jetson Orin Nano Developer Kit that was originally flashed as
# a plain devkit and later OTA-upgraded.
#
# Background: OTA bootloader updates select their firmware capsule from the
# board name recorded at flash time in /etc/nv_boot_control.conf. A devkit
# flashed before JetPack 6.2 says "jetson-orin-nano-devkit-", so every OTA
# applies TEGRA_BL_3767.Cap and the QSPI keeps the non-super clock tables
# (EMC capped at 2133 MHz, GPU at 624.75 MHz) even when the kernel boots the
# super DTB and nvpmodel reports 25W — the BPMP silently clamps any attempt
# to raise the caps. This script rewrites the recorded identity to the
# "-super-" variant (so future OTAs stay on the super profile) and stages the
# super capsule — already shipped on-device in /opt/ota_package — for UEFI's
# capsule-on-disk update at the next reboot.
#
# The capsule is staged manually instead of via `fwupdtool install-blob`
# (what NVIDIA's postinst uses) because fwupd demands 2x the capsule size
# free on the ESP, which the stock 63 MB ESP cannot satisfy; the resulting
# UEFI mechanism is identical.
#
# Prerequisite: the super kernel DTB must already be booted (install.sh
# Step 1f + reboot) — the device-tree compatible string must contain "super".
#
# Usage:
#   sudo bash deploy/enable-super-firmware.sh [capsule.Cap]
#   sudo reboot   # UEFI applies the firmware: progress bar, 1-5 minutes.
#                 # DO NOT POWER OFF during that boot.
#                 # (Bootloader A/B slots provide automatic fallback.)
#
# The optional argument is a self-built bootloader capsule (e.g.
# TEGRA_BL_patched.Cap carrying the NVMe cold-boot UEFI patch — see
# deploy/jetson-orin-nano-nvme-cold-boot-fix.md, Part 3). Without it the
# STOCK super capsule shipped in /opt/ota_package is staged; the stock
# capsule does NOT contain the cold-boot patch and REVERTS it if it was
# previously applied.
#
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

EMC_SUPER_RATE=3199000000
CAPSULE_STOCK=/opt/ota_package/t23x/TEGRA_BL_3767_super.Cap
CAPSULE_ARG="${1:-}"
CAPSULE_SRC="${CAPSULE_ARG:-$CAPSULE_STOCK}"
BOOT_CTRL_CONF=/etc/nv_boot_control.conf
ESP_MOUNT=/boot/efi
CAPSULE_DST_DIR="$ESP_MOUNT/EFI/UpdateCapsule"
OSIND_VAR=/sys/firmware/efi/efivars/OsIndications-8be4df61-93ca-11d2-aa0d-00e098032b8c

die() {
    echo -e "${RED}ERROR: $*${NC}" >&2
    exit 1
}

[[ $EUID -eq 0 ]] || die "must run as root (sudo bash deploy/enable-super-firmware.sh)"
[[ -f /etc/nv_tegra_release ]] || die "not a Jetson device"

# Already on super firmware? Nothing to do — unless a capsule was passed
# explicitly (e.g. the cold-boot-patched UEFI), which must be applied even
# when the super clocks are already active.
EMC_MAX_RATE="$(cat /sys/kernel/debug/bpmp/debug/clk/emc/max_rate 2>/dev/null || echo 0)"
if [[ -z "$CAPSULE_ARG" && "$EMC_MAX_RATE" -ge "$EMC_SUPER_RATE" ]]; then
    echo -e "${GREEN}Super firmware already active (EMC max ${EMC_MAX_RATE} Hz) — nothing to do.${NC}"
    echo "(To apply a self-built capsule anyway — e.g. the NVMe cold-boot"
    echo " patched UEFI — pass its path: sudo bash $0 <capsule.Cap>)"
    exit 0
fi

if [[ -z "$CAPSULE_ARG" ]]; then
    echo -e "${YELLOW}Staging NVIDIA's STOCK super capsule. It does NOT contain the NVMe"
    echo -e "cold-boot UEFI patch and REVERTS it if it was previously applied. If this"
    echo -e "device needs that fix, build the patched capsule and re-run with its path"
    echo -e "(see deploy/jetson-orin-nano-nvme-cold-boot-fix.md, Part 3).${NC}"
fi

# The kernel must be running the super DTB: nvpower.sh keys the nvpmodel conf
# off this, and staging super firmware under a non-super kernel is untested.
if ! tr '\0' '\n' < /proc/device-tree/compatible | grep -q -- "-super"; then
    die "the super kernel DTB is not booted (device-tree compatible has no \
'-super'). Run install.sh (Step 1f swaps the FDT in extlinux.conf), reboot, \
then re-run this script."
fi

if [[ -n "$CAPSULE_ARG" ]]; then
    [[ -f "$CAPSULE_SRC" ]] || die "capsule not found at $CAPSULE_SRC"
else
    [[ -f "$CAPSULE_SRC" ]] || die "super capsule not found at $CAPSULE_SRC \
(is nvidia-l4t-bootloader installed and up to date?)"
fi
mountpoint -q "$ESP_MOUNT" || die "ESP is not mounted at $ESP_MOUNT"

# Capsule already staged from a previous run? Just remind about the reboot.
if [[ -f "$CAPSULE_DST_DIR/TEGRA_BL.Cap" ]] \
    && cmp -s "$CAPSULE_DST_DIR/TEGRA_BL.Cap" "$CAPSULE_SRC"; then
    echo -e "${YELLOW}Super capsule already staged — REBOOT to apply it.${NC}"
    exit 0
fi

# 1) Record the super identity so this and future OTA capsule selections use
# the super profile. The boot-config service regenerates this file each boot
# but carries the board name forward from the file itself, so the edit sticks.
if grep -q "jetson-orin-nano-devkit-super-" "$BOOT_CTRL_CONF"; then
    echo "Board identity already jetson-orin-nano-devkit-super-"
elif grep -q "jetson-orin-nano-devkit-" "$BOOT_CTRL_CONF"; then
    cp "$BOOT_CTRL_CONF" "${BOOT_CTRL_CONF}.pre-super.bak"
    sed -i "s|jetson-orin-nano-devkit-|jetson-orin-nano-devkit-super-|g" \
        "$BOOT_CTRL_CONF"
    echo -e "${GREEN}Board identity updated to devkit-super (backup: ${BOOT_CTRL_CONF}.pre-super.bak)${NC}"
else
    die "unexpected board identity in $BOOT_CTRL_CONF — this script only \
supports the Orin Nano Developer Kit"
fi

# 2) Stage the capsule for UEFI capsule-on-disk.
CAPSULE_SIZE="$(stat -c %s "$CAPSULE_SRC")"
ESP_FREE="$(df --output=avail -B1 "$ESP_MOUNT" | tail -1)"
[[ "$ESP_FREE" -ge "$CAPSULE_SIZE" ]] || die "not enough space on $ESP_MOUNT \
(${ESP_FREE} B free, capsule is ${CAPSULE_SIZE} B)"
mkdir -p "$CAPSULE_DST_DIR"
cp "$CAPSULE_SRC" "$CAPSULE_DST_DIR/TEGRA_BL.Cap"
sync

# 3) Set the EFI_OS_INDICATIONS_FILE_CAPSULE_DELIVERY_SUPPORTED bit (0x4).
# efivarfs format: 4 bytes attributes (0x7 = NV+BS+RT) + 8 bytes value.
# Preserve any already-set indication bits (all defined bits are in the low
# byte on this platform).
existing=0
if [[ -f "$OSIND_VAR" ]]; then
    chattr -i "$OSIND_VAR" 2>/dev/null || true
    existing="$(od -An -tu1 -j4 -N1 "$OSIND_VAR" | tr -d ' ')"
fi
lowbyte="$(printf '\\x%02x' $((existing | 4)))"
printf "\x07\x00\x00\x00${lowbyte}\x00\x00\x00\x00\x00\x00\x00" > "$OSIND_VAR"

echo ""
echo -e "${GREEN}Super firmware capsule staged.${NC}"
echo ""
echo "=========================================================="
echo "REBOOT NOW TO APPLY THE FIRMWARE UPDATE."
echo "UEFI WILL SHOW A PROGRESS BAR FOR 1-5 MINUTES."
echo "DO NOT POWER OFF THE DEVICE DURING THAT BOOT."
echo "=========================================================="
echo ""
echo "Verify afterwards:"
echo "  sudo nvpmodel -q                                            # 25W"
echo "  sudo cat /sys/kernel/debug/bpmp/debug/clk/emc/max_rate      # 3199000000"
if [[ -n "$CAPSULE_ARG" ]]; then
    echo "  sudo efibootmgr -v                # Timeout: 15 seconds, NO PXE/HTTP entries"
    echo ""
    echo "Then pin the bootloader package so an apt upgrade cannot revert the patch:"
    echo "  sudo apt-mark hold nvidia-l4t-bootloader"
fi
