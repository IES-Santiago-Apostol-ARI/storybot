#!/bin/bash
#
# generate-patched-capsule.sh — HOST-SIDE (dev machine, x86) helper that
# packages the archived NVMe cold-boot-fix artifacts into a UEFI bootloader
# capsule (TEGRA_BL_patched.Cap) using an L4T BSP tree.
#
# It copies deploy/firmware/r<release>/{uefi_t23x_general_RELEASE.bin,
# L4TConfiguration.dtbo} into the BSP and runs NVIDIA's BUP + capsule
# generation — no BSP re-download and no Docker EDK2 build needed (see
# deploy/firmware/r<release>/README.md and
# deploy/jetson-orin-nano-nvme-cold-boot-fix.md, Part 3).
#
# The artifacts MUST match the BSP's release, so the release is read from the
# BSP itself (nv_tegra/bsp_version) rather than hardcoded: pairing e.g. the
# R36.5.0 UEFI with an R36.5.2 BSP yields a capsule whose UEFI does not match
# the kernel/userspace on disk. If no archive exists for the BSP's release,
# build one first (doc Parts 1-2) — this script will not fall back.
#
# Usage:
#   sudo bash deploy/generate-patched-capsule.sh [path-to-Linux_for_Tegra]
#   # default BSP path: /datos/Linux_for_Tegra
#   # L4T_RELEASE=36.5.2 overrides autodetection (deliberate mismatch only)
#
# Output: deploy/firmware/r<release>/TEGRA_BL_patched.Cap
# Then, on the Jetson (super kernel DTB already booted — install.sh + reboot):
#   sudo bash deploy/enable-super-firmware.sh /path/to/TEGRA_BL_patched.Cap
#
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BSP="${1:-/datos/Linux_for_Tegra}"

die() {
    echo -e "${RED}ERROR: $*${NC}" >&2
    exit 1
}

# Resolve and validate everything before demanding root, so a wrong path or a
# missing archive fails immediately rather than after a sudo prompt.
[[ -f "$BSP/flash.sh" ]] || die "no BSP at $BSP (expected Linux_for_Tegra tree; \
pass its path as first argument)"

# Read the release from the BSP so the artifacts can never be paired with a
# BSP they were not built against. L4T_RELEASE overrides it deliberately.
if [[ -n "${L4T_RELEASE:-}" ]]; then
    RELEASE="$L4T_RELEASE"
    echo -e "${YELLOW}L4T_RELEASE override in effect: $RELEASE (BSP autodetection \
skipped)${NC}"
else
    VERSION_FILE="$BSP/nv_tegra/bsp_version"
    [[ -f "$VERSION_FILE" ]] || die "cannot determine the BSP release: \
$VERSION_FILE not found. Pass L4T_RELEASE=<x.y.z> to override."
    # shellcheck disable=SC2016
    RELEASE="$(awk -F= '
        $1 == "BSP_BRANCH" { branch = $2 }
        $1 == "BSP_MAJOR"  { major  = $2 }
        $1 == "BSP_MINOR"  { minor  = $2 }
        END { if (branch != "" && major != "" && minor != "")
                  print branch "." major "." minor }
    ' "$VERSION_FILE")"
    [[ -n "$RELEASE" ]] || die "could not parse BSP_BRANCH/MAJOR/MINOR from \
$VERSION_FILE. Pass L4T_RELEASE=<x.y.z> to override."
fi

FW_DIR="$SCRIPT_DIR/firmware/r$RELEASE"
CAPSULE_OUT="$FW_DIR/TEGRA_BL_patched.Cap"

echo -e "${GREEN}BSP release $RELEASE — using artifacts from $FW_DIR${NC}"

[[ -f "$FW_DIR/uefi_t23x_general_RELEASE.bin" ]] || die "no archived artifacts \
for L4T R$RELEASE at $FW_DIR. Build them first (see \
deploy/jetson-orin-nano-nvme-cold-boot-fix.md, Parts 1-2) — artifacts from \
another release must NOT be used with this BSP."

[[ $EUID -eq 0 ]] || die "must run as root (the L4T BUP/capsule tools require it)"

# Verify the archived artifacts before flashing them anywhere.
(cd "$FW_DIR" && sha256sum -c SHA256SUMS) || die "artifact checksum mismatch in $FW_DIR"

# Drop the pre-built artifacts into the BSP.
cp "$FW_DIR/uefi_t23x_general_RELEASE.bin" "$BSP/bootloader/uefi_jetson.bin"
cp "$FW_DIR/L4TConfiguration.dtbo" "$BSP/kernel/dtb/L4TConfiguration.dtbo"
echo -e "${GREEN}Patched UEFI + L4TConfiguration.dtbo copied into the BSP${NC}"

cd "$BSP"

# Host prerequisites for payload generation (idempotent).
./tools/l4t_flash_prerequisites.sh

# Bootloader update payload, restricted to one board with -b.
#
# Do NOT drop the -b: an unrestricted `l4t_generate_soc_bup.sh t23x` builds a
# multi-spec payload covering every t23x board (all AGX Orin variants, every
# Orin Nano SKU/chipsku), producing a ~128 MB capsule. The Jetson's ESP is
# only 63 MB, so enable-super-firmware.sh cannot stage it — it aborts with
# "not enough space on /boot/efi". Restricted to the super board the payload
# is ~36 MB and the capsule ~37 MB, which fits with room to spare.
#
# Capsule payload selection keys off COMPATIBLE_SPEC in
# /etc/nv_boot_control.conf ("...jetson-orin-nano-devkit-super-"), so the
# narrowed payload still matches the device. Override for a different board.
BOARD="${L4T_BOARD:-jetson-orin-nano-devkit-super}"
echo -e "${GREEN}Generating BUP for board $BOARD${NC}"
./l4t_generate_soc_bup.sh -b "$BOARD" t23x

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
echo "The capsule sits in $FW_DIR/. It is gitignored (~128 MB, over GitHub's"
echo "100 MB limit) — the artifacts beside it are the committed source of"
echo "truth; re-run this script to regenerate the capsule when needed."
