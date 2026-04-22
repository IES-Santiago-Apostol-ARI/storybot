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

### 1.5 Flash the QSPI bootloader (both A and B slots)

Put the Jetson in recovery mode:

1. Shut down the Jetson.
2. Connect USB-C cable between the Jetson and host PC.
3. Hold the **recovery button** (middle button on dev kit).
4. Press and release the **power button**.
5. Release the recovery button after ~2 seconds.

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

**Verify the patch is in the binary:**

```bash
strings images/uefi_t23x_general_RELEASE.bin | grep "retry"
# Should show: PCIe Link not up, retry %d/20...
```

Exit Docker:

```bash
exit
```

### 2.6 Flash the custom UEFI

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
