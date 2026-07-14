#!/bin/bash
#
# generate-patched-capsule.sh — HOST-SIDE (dev machine, x86) helper that
# packages the archived NVMe cold-boot-fix artifacts into a UEFI bootloader
# capsule (TEGRA_BL_patched.Cap) using an L4T R36.5.0 BSP tree.
#
# It copies deploy/firmware/r36.5.0/{uefi_t23x_general_RELEASE.bin,
# L4TConfiguration.dtbo} into the BSP and runs NVIDIA's BUP + capsule
# generation — no BSP re-download and no Docker EDK2 build needed (see
# deploy/firmware/r36.5.0/README.md and
# deploy/jetson-orin-nano-nvme-cold-boot-fix.md, Part 3).
#
# The BSP tree MUST match the artifacts' release (R36.5.0 / JetPack 6.2);
# for any other release rebuild the artifacts first (doc Parts 1-2).
#
# Usage:
#   sudo bash deploy/generate-patched-capsule.sh [path-to-Linux_for_Tegra]
#   # default BSP path: /datos/Linux_for_Tegra
#
# Output: deploy/firmware/r36.5.0/TEGRA_BL_patched.Cap
# Then, on the Jetson (super kernel DTB already booted — install.sh + reboot):
#   sudo bash deploy/enable-super-firmware.sh /path/to/TEGRA_BL_patched.Cap
#
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FW_DIR="$SCRIPT_DIR/firmware/r36.5.0"
BSP="${1:-/datos/Linux_for_Tegra}"
CAPSULE_OUT="$FW_DIR/TEGRA_BL_patched.Cap"

die() {
    echo -e "${RED}ERROR: $*${NC}" >&2
    exit 1
}

[[ $EUID -eq 0 ]] || die "must run as root (the L4T BUP/capsule tools require it)"
[[ -f "$BSP/flash.sh" ]] || die "no BSP at $BSP (expected Linux_for_Tegra tree; \
pass its path as first argument)"
[[ -f "$FW_DIR/uefi_t23x_general_RELEASE.bin" ]] || die "archived artifacts \
missing at $FW_DIR"

echo -e "${YELLOW}Reminder: the BSP at $BSP must be L4T R36.5.0 — the archived \
artifacts are only valid for that release.${NC}"

# Verify the archived artifacts before flashing them anywhere.
(cd "$FW_DIR" && sha256sum -c SHA256SUMS) || die "artifact checksum mismatch in $FW_DIR"

# Drop the pre-built artifacts into the BSP.
cp "$FW_DIR/uefi_t23x_general_RELEASE.bin" "$BSP/bootloader/uefi_jetson.bin"
cp "$FW_DIR/L4TConfiguration.dtbo" "$BSP/kernel/dtb/L4TConfiguration.dtbo"
echo -e "${GREEN}Patched UEFI + L4TConfiguration.dtbo copied into the BSP${NC}"

cd "$BSP"

# Host prerequisites for payload generation (idempotent).
./tools/l4t_flash_prerequisites.sh

# Multi-spec bootloader update payload (covers the -super TNSPEC too).
./l4t_generate_soc_bup.sh t23x

# Wrap it as a UEFI capsule.
./generate_capsule/l4t_generate_soc_capsule.sh \
    -i bootloader/payloads_t23x/bl_only_payload \
    -o "$CAPSULE_OUT" t234

[[ -f "$CAPSULE_OUT" ]] || die "capsule generation did not produce $CAPSULE_OUT"

echo ""
echo -e "${GREEN}Capsule generated: $CAPSULE_OUT${NC}"
echo ""
echo "Next, on the Jetson (install.sh + reboot first so the super DTB is booted):"
echo "  scp $CAPSULE_OUT <user>@<jetson>:~/"
echo "  sudo bash deploy/enable-super-firmware.sh ~/TEGRA_BL_patched.Cap"
echo "  sudo reboot        # progress bar 1-5 min — DO NOT POWER OFF"
echo "  sudo apt-mark hold nvidia-l4t-bootloader"
echo ""
echo "The capsule sits in deploy/firmware/r36.5.0/ — commit it (30-70 MB binary)"
echo "if you want the repo self-sufficient without the BSP tree."
