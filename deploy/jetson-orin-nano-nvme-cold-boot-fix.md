# Jetson Orin Nano — NVMe Cold Boot Fix

## Problem

The Jetson Orin Nano Developer Kit fails to boot from NVMe SSD on cold boot (full power off/on), dropping to the UEFI shell instead. Warm reboots work fine. This is caused by the Kingston SNV3S500G (and potentially other NVMe SSDs) being slow to initialize its PCIe link after a cold power-on. The UEFI firmware doesn't wait long enough for the SSD to become ready.

## Environment

- **Board:** NVIDIA Jetson Orin Nano Developer Kit
- **L4T:** R36.5.0 (JetPack 6.2)
- **SSD:** Kingston SNV3S500G (firmware P3AR2B12)
- **Host PC:** Ubuntu (20.04/22.04/24.04) with Docker installed

## Overview of Fixes Applied

1. **L4TConfiguration.dtbo** — Set boot priority to NVMe only (removes PXE/HTTP network boot entries) and increase UEFI timeout to 15 seconds.
2. **Custom UEFI firmware** — Increase PCIe post-PERST# delay from 200ms to 5000ms and add a retry loop (20 × 500ms) for PCIe link detection.

> **Pre-built artifacts:** for L4T R36.5.0 all build outputs (patched UEFI
> binary, modified L4TConfiguration.dtbo, source patch) are archived in
> `deploy/firmware/r36.5.0/` — see its README. Parts 1.1–1.4 and 2.1–2.5
> (BSP download, dtbo editing, Docker EDK2 build) only need to be redone for
> a different L4T release.

## Choosing a Route — READ THIS FIRST

There are two ways to get the fixes into QSPI. **Do ONE of them, not both**
(on 2026-07-13 we did the recovery flash of 1.5 first and then still had to do
the whole flash again for the patched UEFI — pure duplicated work):

- **Route A — Capsule (RECOMMENDED, also for a brand-new Jetson):** build
  everything on the host (steps 1.1–1.4 and 2.1–2.5), generate a self-built
  capsule (3.2), and apply it from the running Jetson with
  `deploy/enable-super-firmware.sh <capsule>` (3.3). ONE reboot installs the
  modified L4TConfiguration, the patched UEFI **and** the Super clock tables
  in a single update. No recovery mode, no USB cable. **Skip steps 1.5 and
  2.6 entirely.** This works even on a device suffering the cold-boot bug —
  it boots fine on warm reboots. On a new device, run `deploy/install.sh`
  and reboot first (it selects the super kernel DTB, a prerequisite of the
  script).

- **Route B — Recovery-mode flash (rescue only):** steps 1.5 and 2.6, with
  the Jetson in recovery mode over USB. Only needed when the device has no
  bootable OS at all. This route does NOT install the Super clock tables —
  you would still need a capsule afterwards, and applying NVIDIA's *stock*
  super capsule reverts this fix (see Part 3) — another reason to prefer
  Route A.

---

## Part 1: Modify L4TConfiguration.dtbo

This removes network boot entries that the UEFI regenerates on every cold boot, and increases the boot timeout.

### 1.1 Download and extract the BSP on the host PC

```bash
mkdir -p ~/jetson && cd ~/jetson
wget https://developer.nvidia.com/downloads/embedded/l4t/r36_release_v5.0/release/jetson_linux_r36.5.0_aarch64.tbz2
tar xf jetson_linux_r36.5.0_aarch64.tbz2
cd Linux_for_Tegra
```

### 1.2 Decompile the existing L4TConfiguration.dtbo

```bash
./kernel/dtc -I dtb -O dts -o kernel/dtb/L4TConfiguration.dts kernel/dtb/L4TConfiguration.dtbo
```

> **Note:** You will see a warning about `unit_address_vs_reg`. This is harmless — ignore it.

### 1.3 Edit L4TConfiguration.dts

Open `kernel/dtb/L4TConfiguration.dts` and make two changes:

**Change 1:** Find the `DefaultBootPriority` section inside `gNVIDIATokenSpaceGuid` and change:

```
data = "usb,nvme,emmc,sd,ufs";
```

to:

```
data = "nvme";
```

**Change 2:** Add a `gEfiGlobalVariableGuid` block as a sibling to `gNVIDIATokenSpaceGuid` inside the `variables` node:

```
gEfiGlobalVariableGuid {
    Timeout {
        data = [ 0f 00 ];
        runtime;
        locked;
    };
};
```

The `[ 0f 00 ]` is 15 in little-endian UINT16 (15-second timeout).

The final `variables` section should look like:

```dts
variables {
    gNVIDIAPublicVariableGuid {
        /* ... existing entries unchanged ... */
    };

    gNVIDIATokenSpaceGuid {
        DefaultBootPriority {
            data = "nvme";
            locked;
        };
    };

    gEfiGlobalVariableGuid {
        Timeout {
            data = [ 0f 00 ];
            runtime;
            locked;
        };
    };
};
```

### 1.4 Recompile the .dtbo

```bash
./kernel/dtc -I dts -O dtb -o kernel/dtb/L4TConfiguration.dtbo kernel/dtb/L4TConfiguration.dts
```

### 1.5 Flash the QSPI bootloader (both A and B slots) — Route B ONLY

> **Route A (capsule) users: SKIP this step.** The capsule generated in 3.2
> folds the modified L4TConfiguration.dtbo into the bootloader payload —
> recovery-flashing here is redundant, and at this point you would flash the
> *stock* UEFI anyway (the patched one isn't built until Part 2).

Put the Jetson in recovery mode:
1. Apaga la Jetson y desconéctala de la corriente.
2. Asegúrate de que el SSD NVMe de 500 GB está instalado en la ranura M.2.
3. Localiza el header de J14 (12 pines) en la carrier board.
4. Cortocircuita los pines **FC REC** y **GND** (pines 9 y 10) con un jumper o cable.
5. Conecta el cable USB-C de la Jetson al puerto USB-A del PC host.
6. Conecta la fuente de alimentación a la Jetson para encenderla.
7. Deja el jumper conectado hasta que el flasheo comience.


Verify:

```bash
lsusb | grep -i nvidia
# Should show "NVIDIA Corp. APX"
```

Flash:

```bash
cd ~/jetson/Linux_for_Tegra

# Flash A slot
sudo ./flash.sh -k A_cpu-bootloader \
  -c bootloader/generic/cfg/flash_t234_qspi_nvme.xml \
  jetson-orin-nano-devkit nvme0n1p1

# Put back in recovery mode, then flash B slot
sudo ./flash.sh -k B_cpu-bootloader \
  -c bootloader/generic/cfg/flash_t234_qspi_nvme.xml \
  jetson-orin-nano-devkit nvme0n1p1
```

> **Important:** The `-k A_cpu-bootloader` / `-k B_cpu-bootloader` flags mean only the bootloader in QSPI flash is written. The NVMe SSD data is NOT touched.

---

## Part 2: Build Custom UEFI with PCIe Delay Patch

This is needed because the L4TConfiguration changes alone are not sufficient — the SSD needs more time for PCIe link initialization on cold boot.

### 2.1 Install Docker on the host PC

```bash
sudo apt install docker.io
sudo usermod -aG docker $USER
# Log out and back in for group to take effect
```

### 2.2 Set up the Docker build environment

```bash
export EDK2_DEV_IMAGE="ghcr.io/tianocore/containers/ubuntu-22-dev:latest"
export EDK2_USER_ARGS="-v \"${HOME}\":\"${HOME}\" -e EDK2_DOCKER_USER_HOME=\"${HOME}\""
export EDK2_BUILD_ROOT="${HOME}/nvidia-uefi-build"
export EDK2_BUILDROOT_ARGS="-v \"${EDK2_BUILD_ROOT}\":\"${EDK2_BUILD_ROOT}\""
mkdir -p ${EDK2_BUILD_ROOT}
alias edk2_docker="docker run -it --rm -w \"\$(pwd)\" ${EDK2_BUILDROOT_ARGS} ${EDK2_USER_ARGS} \"${EDK2_DEV_IMAGE}\""

# Test
edk2_docker echo hello
```

### 2.3 Clone the UEFI source

We clone the repos manually with git (avoids edkrepo configuration issues):

```bash
mkdir -p ~/nvidia-uefi-build/nvidia-uefi && cd ~/nvidia-uefi-build/nvidia-uefi

git clone https://github.com/NVIDIA/edk2-nvidia.git -b r36.5
git clone https://github.com/NVIDIA/edk2.git -b r36.5
git clone https://github.com/NVIDIA/edk2-platforms.git -b r36.5
git clone https://github.com/NVIDIA/edk2-non-osi.git -b r36.5
git clone https://github.com/NVIDIA/edk2-nvidia-non-osi.git -b r36.5
git clone https://github.com/NVIDIA/edk2-infineon.git -b r36.5
git clone https://github.com/NVIDIA/edk2-redfish-client.git -b r36.5

# Initialize edk2 submodules
cd edk2
git submodule update --init --recursive
cd ..
```

> **Note:** If `-b r36.5` fails for `edk2-infineon` or `edk2-redfish-client`, clone without the branch flag.

### 2.4 Apply the PCIe delay patch

The file to patch is `edk2-nvidia/Silicon/NVIDIA/Drivers/PcieDWControllerDxe/PcieControllerDxe.c`.

**Patch 1 — Increase post-PERST# delay from 200ms to 5000ms:**

```bash
sed -i 's/DeviceDiscoveryThreadMicroSecondDelay (200000);/DeviceDiscoveryThreadMicroSecondDelay (5000000);/' \
  edk2-nvidia/Silicon/NVIDIA/Drivers/PcieDWControllerDxe/PcieControllerDxe.c
```

> **Note:** This `sed` replaces all instances of `200000` in this file. Verify the change is in the right place (after the "de-assert RST" PERST# section around line 791).

**Patch 2 — Add retry loop before the CheckLinkUp failure path:**

```bash
python3 << 'EOF'
filepath = "edk2-nvidia/Silicon/NVIDIA/Drivers/PcieDWControllerDxe/PcieControllerDxe.c"

with open(filepath, 'r') as f:
    content = f.read()

old = """  if (!CheckLinkUp (Private)) {
    UINT32  tmp;
    UINT32  offset;"""

new = """  {
    UINT32 RetryCount;
    for (RetryCount = 0; RetryCount < 20; RetryCount++) {
      if (CheckLinkUp (Private)) {
        break;
      }
      DEBUG ((DEBUG_INFO, "PCIe Link not up, retry %d/20...\\n", RetryCount + 1));
      DeviceDiscoveryThreadMicroSecondDelay (500000);
    }
  }

  if (!CheckLinkUp (Private)) {
    UINT32  tmp;
    UINT32  offset;"""

if old in content:
    content = content.replace(old, new, 1)
    with open(filepath, 'w') as f:
        f.write(content)
    print("Patch applied successfully!")
else:
    print("ERROR: Could not find the target code to patch")
EOF
```

**Verify both patches:**

```bash
grep -n "5000000\|RetryCount < 20\|500000" \
  edk2-nvidia/Silicon/NVIDIA/Drivers/PcieDWControllerDxe/PcieControllerDxe.c
```

### 2.5 Build the UEFI firmware

Enter Docker interactively:

```bash
edk2_docker bash
```

Inside the Docker shell:

```bash
cd ~/nvidia-uefi-build/nvidia-uefi

# Create venv and fix setuptools
python3 -m venv venv
venv/bin/pip install --upgrade pip "setuptools<70"
venv/bin/pip install -r edk2/pip-requirements.txt
venv/bin/pip install kconfiglib

# Set environment
export WORKSPACE="${HOME}/nvidia-uefi-build/nvidia-uefi"
export PYTHONPATH="${WORKSPACE}/edk2-nvidia/Silicon/NVIDIA:${PYTHONPATH}"
export CROSS_COMPILER_PREFIX=/usr/bin/aarch64-linux-gnu-
export UEFI_SKIP_VENV=1
source venv/bin/activate

# Update stuart
stuart_update -c edk2-nvidia/Platform/NVIDIA/Tegra/PlatformBuild.py

# Build basetools
python edk2/BaseTools/Edk2ToolsBuild.py -t GCC

# Build UEFI
edk2-nvidia/Silicon/NVIDIA/scripts/build_stuart.sh \
  edk2-nvidia/Platform/NVIDIA/Tegra/PlatformBuild.py \
  --init-defconfig edk2-nvidia/Platform/NVIDIA/Tegra/DefConfigs/t23x_general.defconfig
```

The output binary will be at `images/uefi_t23x_general_RELEASE.bin`.

**Verify the patch was compiled in:**

```bash
strings Build/t23x_general/RELEASE_GCC/AARCH64/PcieControllerDxe.efi | grep "retry"
# Should show: PCIe Link not up, retry %d/20...
```

> **Note:** Do NOT run `strings` on `images/uefi_t23x_general_RELEASE.bin` for this
> check — the DXE drivers are packed into an LZMA-compressed firmware volume inside
> the composed image, so the string is invisible there even on a correctly patched
> build. Check the built driver `.efi` above instead.

Exit Docker:

```bash
exit
```

### 2.6 Flash the custom UEFI — Route B ONLY

> **Route A (capsule) users: SKIP this step** and continue with 3.2 — the
> capsule delivers this same binary without recovery mode.

```bash
cd ~/jetson/Linux_for_Tegra

# Copy the custom UEFI binary
cp ~/nvidia-uefi-build/nvidia-uefi/images/uefi_t23x_general_RELEASE.bin \
   bootloader/uefi_jetson.bin

# Put Jetson in recovery mode, then:
sudo ./flash.sh -k A_cpu-bootloader \
  -c bootloader/generic/cfg/flash_t234_qspi_nvme.xml \
  jetson-orin-nano-devkit nvme0n1p1

# Recovery mode again, then:
sudo ./flash.sh -k B_cpu-bootloader \
  -c bootloader/generic/cfg/flash_t234_qspi_nvme.xml \
  jetson-orin-nano-devkit nvme0n1p1
```

### 2.7 Test

1. Unplug power completely.
2. Wait a few seconds.
3. Plug power back in.
4. The Jetson should boot from NVMe without dropping to the UEFI shell.

---

## Part 3: The Capsule Route (Route A — new device, or reapplying after a capsule regression)

This is the recommended way to install the fix, whether on a brand-new Jetson
or after a firmware capsule update wiped it. The self-built capsule carries
the modified L4TConfiguration (Part 1), the patched UEFI (Part 2) **and** the
Super clock tables in one update — build it once and archive the `.Cap`; it
can be reused on any Orin Nano devkit running the same L4T release.

**Any QSPI firmware capsule update reverts this entire fix** — it replaces the
patched UEFI (Part 2) *and* the L4TConfiguration defaults (Part 1) with
NVIDIA's stock build. This happened on 2026-07-11 when
`deploy/enable-super-firmware.sh` applied the stock super capsule to unlock
the 25W Super clocks (EMC 3199 MHz / GPU 918 MHz): the cold-boot PXE/shell
drop returned immediately. Telltale signs of stock firmware: `sudo
efibootmgr -v` shows regenerated PXE/HTTP boot entries and `Timeout: 5
seconds` instead of 15.

The fix and the Super clocks are NOT mutually exclusive: the Super profile
lives in the BPMP firmware clock tables, the cold-boot patch lives in the
UEFI binary. A self-generated capsule containing the patched UEFI keeps both,
because capsule payload selection keys off `/etc/nv_boot_control.conf`, which
already says `jetson-orin-nano-devkit-super-`.

This route needs **no recovery mode and no USB cable** — the capsule is
applied from the running Jetson, and the A/B bootloader slots give automatic
fallback if it fails.

### 3.1 Rebuild the patched UEFI (host PC)

**On L4T R36.5.0, skip the builds** — copy the archived artifacts from
`deploy/firmware/r36.5.0/` into the BSP (see that README) and go straight
to 3.2. Otherwise: follow **Part 1** (steps 1.1–1.4: BSP download +
L4TConfiguration edits) and **Part 2** (steps 2.1–2.5: Docker EDK2 build
with the PCIe patches) exactly as written above. Stop before 2.6 — do NOT
recovery-flash. You end with:

- `~/jetson/Linux_for_Tegra/kernel/dtb/L4TConfiguration.dtbo` (modified)
- `~/nvidia-uefi-build/nvidia-uefi/images/uefi_t23x_general_RELEASE.bin`
  (patched; verify via the built driver as described in 2.5 —
  `strings Build/t23x_general/RELEASE_GCC/AARCH64/PcieControllerDxe.efi | grep retry`)

The L4TConfiguration.dtbo gets folded into the cpu-bootloader image at
payload-generation time, so the capsule carries both Part 1 and Part 2.

### 3.2 Generate the capsule (host PC)

**On L4T R36.5.0 this whole section is one command** — it copies the archived
artifacts into the BSP and runs everything below:

```bash
sudo bash deploy/generate-patched-capsule.sh [path-to-Linux_for_Tegra]
# output: deploy/firmware/r36.5.0/TEGRA_BL_patched.Cap
```

Manual steps (any release, after building Parts 1–2 yourself):

```bash
cd ~/jetson/Linux_for_Tegra

# Patched UEFI in place of the stock binary
cp ~/nvidia-uefi-build/nvidia-uefi/images/uefi_t23x_general_RELEASE.bin \
   bootloader/uefi_jetson.bin

# Host prerequisites for payload generation (once)
sudo ./tools/l4t_flash_prerequisites.sh

# Multi-spec bootloader update payload (covers the -super TNSPEC too)
sudo ./l4t_generate_soc_bup.sh t23x

# Wrap it as a UEFI capsule
sudo ./generate_capsule/l4t_generate_soc_capsule.sh \
  -i bootloader/payloads_t23x/bl_only_payload \
  -o ./TEGRA_BL_patched.Cap t234
```

Copy it over: `scp TEGRA_BL_patched.Cap ari@<jetson>:/home/ari/`

Archive `TEGRA_BL_patched.Cap` somewhere safe — with it, provisioning the
next Jetson needs none of the host-side build steps.

### 3.3 Stage and apply (on the Jetson)

`deploy/enable-super-firmware.sh` does the staging (UEFI capsule-on-disk;
fwupd can't be used — the 63 MB ESP is too small for its 2x-size check).
Pass it the patched capsule — run WITHOUT the argument it stages NVIDIA's
stock capsule, which reverts this fix:

```bash
sudo bash deploy/enable-super-firmware.sh /home/ari/TEGRA_BL_patched.Cap
sudo reboot
# UEFI shows a progress bar for 1-5 minutes. DO NOT POWER OFF.
```

On a brand-new device the script also rewrites the board identity in
`/etc/nv_boot_control.conf` to the `-super-` variant (so this and future
capsule selections pick the super payload). It requires the super kernel DTB
to be booted already — `install.sh` step 1f + reboot.

### 3.4 Verify

```bash
sudo nvbootctrl dump-slots-info   # bootloader slot flipped, update status 1
sudo efibootmgr -v                # Timeout: 15 seconds, NO PXE/HTTP entries
sudo nvpmodel -q                  # 25W (Super profile survived)
sudo cat /sys/kernel/debug/bpmp/debug/clk/emc/max_rate   # 3199000000
```

Then the real test: full shutdown, unplug power, wait a few seconds, plug
back in — it must boot straight from NVMe.

### 3.5 Prevent the next regression

An apt upgrade of `nvidia-l4t-bootloader` stages a stock capsule again and
silently undoes the patch. Pin it:

```bash
sudo apt-mark hold nvidia-l4t-bootloader
```

Unhold only when deliberately taking a bootloader update — and re-run this
Part 3 afterwards.

---

## Temporary Workaround (USB Stick)

If you need a quick fix before applying the UEFI patch, you can use a USB stick with a `startup.nsh` script. When the UEFI shell can't find the NVMe, it looks for `startup.nsh` on any available filesystem (including USB):

1. Format a USB drive as FAT32.
2. Create a file `startup.nsh` with a single line: `reset`
3. Plug the USB into the Jetson and leave it plugged in.

On cold boot, if the NVMe isn't ready, UEFI drops to the shell, finds `startup.nsh` on the USB, executes `reset`, and the warm reboot finds the NVMe.

---

## Diagnostic Commands

Useful commands for debugging boot issues:

```bash
# Check current boot order and timeout (on the Jetson)
sudo efibootmgr -v

# Check L4T version
cat /etc/nv_tegra_release

# Check SSD model and firmware
sudo nvme id-ctrl /dev/nvme0 | grep -i -E "mn|fr|sn"

# In UEFI shell: re-scan devices
map -r

# In UEFI shell: list loaded drivers
drivers

# In UEFI shell: check firmware version
ver
```

## Technical Details

The root cause is a race condition in the UEFI PCIe initialization. The Jetson's UEFI firmware de-asserts PERST# (PCIe reset), waits a fixed time, then checks if the NVMe SSD's PCIe link is active. Some SSDs (like the Kingston SNV3S500G) need longer than the default 200ms to bring up their PCIe link after a cold power-on. On warm reboots, the SSD doesn't fully power down, so it initializes much faster.

The patch modifies `PcieDWControllerDxe/PcieControllerDxe.c` (the DesignWare PCIe controller driver for Tegra T234) to:

1. Wait 5 seconds after de-asserting PERST# (up from 200ms).
2. Retry link detection 20 times with 500ms intervals (up to 10 additional seconds) before giving up.

This gives the SSD up to 15 seconds total to establish its PCIe link on cold boot.
