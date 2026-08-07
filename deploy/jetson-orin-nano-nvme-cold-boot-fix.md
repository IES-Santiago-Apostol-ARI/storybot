# Jetson Orin Nano — NVMe Cold Boot Fix

## Problem

The Jetson Orin Nano Developer Kit fails to boot from NVMe SSD on cold boot (full power off/on), dropping to the UEFI shell instead. Warm reboots work fine. This is caused by the Kingston SNV3S500G (and potentially other NVMe SSDs) being slow to initialize its PCIe link after a cold power-on. The UEFI firmware doesn't wait long enough for the SSD to become ready.

## Environment

- **Board:** NVIDIA Jetson Orin Nano Developer Kit
- **L4T:** fix originally built on R36.5.0 (JetPack 6.2). The device now runs
  **R36.5.2** (kernel 5.15.199) since the 2026-08-06 `apt dist-upgrade` — see
  Part 3.5. The archived artifacts are still R36.5.0 only.
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
>
> **The two artifacts are coupled to the release very differently — this is
> the single most confusing thing in this document:**
>
> - `L4TConfiguration.dtbo` **is** release-coupled. It is derived from the
>   BSP's own `kernel/dtb/L4TConfiguration.dtbo`, so it must be re-derived
>   (Part 1) for every L4T release.
> - `uefi_t23x_general_RELEASE.bin` is **not** BSP-coupled at all. Part 2
>   builds it purely from the seven edk2 git repos; `Linux_for_Tegra` is never
>   read. It is coupled to the **UEFI source tag** (2.3), which versions
>   independently of L4T — and stops at `r36.5.1`.
>
> So "rebuild for R36.5.2" means: re-derive the dtbo from the R36.5.2 BSP, and
> build the UEFI from the newest available tag. There is no R36.5.2 UEFI
> source to build from and there never will be.
>
> Only R36.5.0 is archived, and no `.Cap` was ever archived (only the inputs
> to it). When you rebuild, archive the resulting artifacts *and*
> `TEGRA_BL_patched.Cap` under `deploy/firmware/r36.5.2/`, and record the UEFI
> source tag in that directory's README — the directory name tracks the BSP
> release, which does *not* imply the UEFI came from a same-named tag.
>
> `deploy/generate-patched-capsule.sh` reads the release from the BSP
> (`nv_tegra/bsp_version`) and looks for `deploy/firmware/r<release>/`. It
> aborts if that directory has no artifacts — it will never fall back to
> another release's UEFI. So archiving under the right directory name is all
> that is needed; there is nothing to edit in the script.

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
From https://developer.nvidia.com/embedded/jetson-linux-r3652

```bash
mkdir -p ~/jetson && cd ~/jetson
wget https://developer.nvidia.com/downloads/embedded/l4t/r36_release_v5.2/releases/Jetson_Linux_r36.5.2_aarch64.tbz2
tar xf Jetson_Linux_r36.5.2_aarch64.tbz2
cd Linux_for_Tegra
```

> **Match the BSP to the release the device runs.** The URL above is R36.5.2
> (`r36_release_v5.2`); other releases live under their own
> `r36_release_vX.Y` path. A BSP that disagrees with the installed
> `nvidia-l4t-*` packages produces a capsule that does not match the
> kernel/userspace on disk. Confirm what the device runs with
> `cat /etc/nv_tegra_release`, and confirm the extracted tree with
> `grep BSP_ Linux_for_Tegra/nv_tegra/bsp_version`.

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

REF=r36.5.1   # newest published UEFI ref — see the note below

for repo in edk2-nvidia edk2 edk2-platforms edk2-non-osi \
            edk2-nvidia-non-osi edk2-infineon edk2-redfish-client; do
  git clone https://github.com/NVIDIA/$repo.git -b "$REF"
done

# Initialize edk2 submodules
cd edk2
git submodule update --init --recursive
cd ..
```

> **Which ref to use (verified 2026-08-07).** `r36.5` and `r36.5.1` are
> **tags**, not branches — `git clone -b` on either lands you on a detached
> HEAD at a fixed commit, and all seven repos carry both, so the loop needs no
> per-repo exception. There is no tag beyond `r36.5.1`: NVIDIA has never
> published UEFI source for R36.5.2, so `r36.5.1` (= `r36.5` plus one
> DisplayDeviceTreeHelperLib fix) is the newest ref available and the one to
> prefer. The original R36.5.0 build used `r36.5`. The branches
> `r36.5-updates` / `r36.5.1-updates` add only CI chores.
>
> This does not weaken the fix: `PcieControllerDxe.c` is the *same blob*
> (`222275dc`, unchanged upstream since 2024-10-31) at `r36.5`, `r36.5.1` and
> `r36.5-updates`, and is the blob the archived R36.5.0 patch was made
> against — so the PCIe timing behaviour you build is identical to the
> R36.5.0 binary that worked.
>
> **Accept this consequence:** building from `r36.5.1` onto an R36.5.2 BSP
> means running an R36.5.1-level UEFI under an R36.5.2 kernel/userspace. The
> R36.5.2 UEFI fix 5412830 (StandaloneMM variable storage, cited in Part 3.5)
> is not in public source and you will not get it. The kernel and userspace
> CVE fixes are unaffected. The alternative — stock R36.5.2 firmware — has no
> cold-boot fix at all.

### 2.4 Apply the PCIe delay patch

The file to patch is `edk2-nvidia/Silicon/NVIDIA/Drivers/PcieDWControllerDxe/PcieControllerDxe.c`.

**Preferred: apply the archived patch.** It is the exact change that produced
the working R36.5.0 binary, and it applies to every ref listed in 2.3:

```bash
cd ~/nvidia-uefi-build/nvidia-uefi/edk2-nvidia
git apply -p1 --ignore-whitespace \
  /datos/storybot/deploy/firmware/r36.5.0/pcie-cold-boot-fix.patch
```

> **`--ignore-whitespace` is required, not optional.** `PcieControllerDxe.c`
> ships with **CRLF** line endings while the archived patch is LF. Without the
> flag both `git apply` and `patch` fail with `different line endings` /
> `patch does not apply`. Same trap in the manual route below: the `sed` in
> Patch 1 is line-ending agnostic and works, but the Patch 2 python heredoc
> matches on `\n` and will **silently print `ERROR: Could not find the target
> code to patch`** against the CRLF file. Read its output — it does not exit
> non-zero.

The manual equivalents follow, for a release where the archived patch no
longer applies.

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
to 3.2. **On R36.5.2 there is no such shortcut** — no R36.5.2 artifacts are
archived, and the R36.5.0 UEFI must not be paired with an R36.5.2 BSP.
Otherwise: follow **Part 1** (steps 1.1–1.4: BSP download +
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

**Once artifacts for the BSP's release are archived, this whole section is one
command** — it copies them into the BSP and runs everything below:

```bash
sudo bash deploy/generate-patched-capsule.sh [path-to-Linux_for_Tegra]
# output: deploy/firmware/r<release>/TEGRA_BL_patched.Cap
```

The release comes from the BSP's `nv_tegra/bsp_version`, so the script picks
`deploy/firmware/r36.5.2/` for an R36.5.2 BSP and **aborts** if that directory
is empty — it never falls back to another release's UEFI. So before running
it on R36.5.2, archive your freshly built `uefi_t23x_general_RELEASE.bin` and
`L4TConfiguration.dtbo` (plus `SHA256SUMS`) under `deploy/firmware/r36.5.2/`.
`L4T_RELEASE=<x.y.z>` overrides the autodetection if you ever need a
deliberate mismatch.

Manual steps (any release, after building Parts 1–2 yourself):

```bash
cd ~/jetson/Linux_for_Tegra

# Patched UEFI in place of the stock binary
cp ~/nvidia-uefi-build/nvidia-uefi/images/uefi_t23x_general_RELEASE.bin \
   bootloader/uefi_jetson.bin

# Host prerequisites for payload generation (once)
sudo ./tools/l4t_flash_prerequisites.sh

# Bootloader update payload for ONE board — the -b is not optional, see below
sudo ./l4t_generate_soc_bup.sh -b jetson-orin-nano-devkit-super t23x

# Wrap it as a UEFI capsule
sudo ./generate_capsule/l4t_generate_soc_capsule.sh \
  -i bootloader/payloads_t23x/bl_only_payload \
  -o ./TEGRA_BL_patched.Cap t234
```

> **The `-b <board>` is mandatory — this bit us on 2026-08-07.** Without it,
> `l4t_generate_soc_bup.sh t23x` builds a multi-spec payload covering *every*
> t23x board (all AGX Orin variants, every Orin Nano SKU/chipsku). The result
> is a **128 MB capsule, and the Jetson's ESP is only 63 MB** — so
> `enable-super-firmware.sh` aborts with `not enough space on /boot/efi` and
> the fix cannot be applied at all. Restricted to the super board the payload
> is ~36 MB and the capsule ~37 MB, staging with 28 MB free.
>
> This is safe because capsule payload selection keys off `COMPATIBLE_SPEC`
> in `/etc/nv_boot_control.conf` (`...jetson-orin-nano-devkit-super-`), which
> the narrowed payload still matches. Confirmed on-device: the update applied,
> the slot flipped A→B, and the Super clocks survived.

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
cat /sys/devices/virtual/dmi/id/bios_version   # the decisive one — see below
sudo nvbootctrl dump-slots-info   # bootloader slot flipped, update status 1
sudo efibootmgr -v                # Timeout: 15 seconds
sudo nvpmodel -q                  # 25W (Super profile survived)
sudo cat /sys/kernel/debug/bpmp/debug/clk/emc/max_rate   # 3199000000
ls /boot/efi/EFI/UpdateCapsule/   # empty — the capsule was consumed
```

**`bios_version` is the check to trust.** It reports the running UEFI build
id — e.g. `r36.5.1-3dfabbec-dirty`, matching
`images/buildid_t23x_general_RELEASE.txt` from your build (`-dirty` is the
PCIe patch). Stock firmware reports NVIDIA's own id. This is direct proof the
patched binary is executing, rather than an inference from side effects, and
it is much faster than the cold-boot test.

> **Do NOT expect the PXE/HTTP entries to disappear after a capsule update.**
> Part 3 above lists "regenerated PXE/HTTP entries" as a tell of stock
> firmware, and that holds after a *recovery flash*, which wipes UEFI NVRAM.
> A capsule update does not: on 2026-08-07 the patched firmware verified good
> by `bios_version` and `Timeout: 15 seconds` still listed all four
> `Boot0001`–`Boot0004` PXE/HTTP entries, left over from the stock firmware.
> `DefaultBootPriority = "nvme"` stops UEFI *creating* such entries; it does
> not delete existing ones. They are harmless — `BootOrder` had the NVMe
> entry first and `BootCurrent` was the NVMe entry. **Use `Timeout` and
> `bios_version` as the tells, not the presence of PXE entries.**

Then the real test: full shutdown, unplug power, wait a few seconds, plug
back in — it must boot straight from NVMe.

### 3.5 Prevent the next regression

An apt upgrade of `nvidia-l4t-bootloader` stages a stock capsule again and
silently undoes the patch. Pin it:

```bash
sudo apt-mark hold nvidia-l4t-bootloader
```

`deploy/install.sh` applies this automatically (Step 11b) on any host where
`nvidia-l4t-bootloader` is installed, so a freshly provisioned Jetson is
protected without remembering to do it by hand. Covered by
`tests/test_install_script.py::TestBootloaderHold`.

Verify the hold is actually in place — this is the step that failed in
2026-08 (see below):

```bash
apt-mark showhold        # must list nvidia-l4t-bootloader
```

Unhold only when deliberately taking a bootloader update — and re-run this
Part 3 afterwards.

#### Regression log: 2026-08-06 (L4T 36.5.0 → 36.5.2) — RESOLVED 2026-08-07

`apt dist-upgrade` upgraded `nvidia-l4t-bootloader` and reverted the patched
UEFI. **The hold above had never actually been applied** — `apt-mark showhold`
was empty — so the documented protection was not in force. Re-applied
2026-08-07.

**Resolution:** rebuilt the UEFI from `r36.5.1` against the R36.5.2 BSP,
generated a capsule and applied it via Route A (no recovery mode, no USB
cable). Verified: `bios_version` = `r36.5.1-3dfabbec-dirty`, `Timeout: 15
seconds`, slot A→B, Super profile intact, and a **full cold boot straight
from NVMe**. Artifacts and provenance in `deploy/firmware/r36.5.2/`.

Two traps found during the restore, both now fixed in the procedure above:

1. **The capsule was 128 MB and could not be staged** — the ESP is 63 MB.
   Cause: `l4t_generate_soc_bup.sh` without `-b` covers every t23x board.
   See the warning in 3.2. This was latent in the documented procedure, not
   something R36.5.2 introduced.
2. **PXE/HTTP entries persist after a capsule update** and are *not* evidence
   the fix failed. See the note in 3.4.

Diagnosis took two wrong turns worth not repeating. The symptom looks like a
PXE / boot-order problem and is not: after a failed cold boot, `efibootmgr`
still showed `BootCurrent: 0007` with the NVMe entry *first*. Boot order is
never the fault. The reliable tells are the two in Part 3 — regenerated
PXE/HTTP entries and `Timeout: 5 seconds` instead of 15 — plus the decisive
one: **a warm `reset` from the UEFI shell fixes it.** That rules out
configuration and points at PCIe link timing every time. Plugging a keyboard
is not what fixes the boot; the second boot is.

#### Restoring after this regression: rebuild vs roll back

R36.5.2 is worth keeping rather than rolling back to R36.5.0. Nothing in it
addresses PCIe/NVMe link timing, so the patch is still required either way,
but it does fix (release notes RN_10698-r36.5.2, §3):

- **5412830** — UEFI assertion error during boot that stops the device at the
  bootloader, occurs randomly, and requires a full firmware reflash to
  recover. Fixes StandaloneMM variable-storage record handling and block erase
  logic. Directly relevant to this board's history — but note you do **not**
  get this one: it lives in the UEFI, and the self-built patched UEFI is
  R36.5.1-level source (see 2.3). It is a reason to keep the R36.5.2 kernel
  and userspace, not a firmware benefit of this route.
- **5602402** — NvMap allocation policy fix for "unable to allocate CUDA0
  buffer" after an APT upgrade. Matters on 8 GB with SD + LLM resident.
- **4840276** — display not resuming after suspend on headless systems.
- Kernel 5.15.185 → 5.15.199, plus the JetPack 6.2.2/6.2.3 CVE fixes
  (CVE-2026-24148 CVSS 8.3, CVE-2026-24154 7.6, CVE-2026-24153).

Unrelated but caught by the same upgrade: `gstreamer1.0-plugins-bad`
(`h264parse`) is no longer pre-installed on 22.04 desktop images (issue
5842995) — install it explicitly if a pipeline breaks.

So: redo parts 1.1–1.4 against the **R36.5.2 BSP** and 2.1–2.5 against the
**`r36.5.1` UEFI tag** (there is no R36.5.2 UEFI source — see the note in
2.3), generate the capsule (3.2), apply it (3.3), and archive the artifacts
*and* the `.Cap` under `deploy/firmware/r36.5.2/` this time.

The `L4TConfiguration.dtbo` in particular must be re-derived from the R36.5.2
BSP — that is the genuinely release-coupled artifact.
`generate-patched-capsule.sh` enforces the pairing: it reads the release from
the BSP and aborts rather than reaching for another release's directory.

The UEFI binary is the looser half. The archived R36.5.0 `.bin` was itself
built from the `r36.5` tag, so reusing it would *not* have been the mismatch
it looks like — the only delta against a fresh `r36.5.1` build is one
DisplayDeviceTreeHelperLib commit, nothing touching PCIe or boot. It was
rebuilt from `r36.5.1` on 2026-08-07 to stay on the newest published source.

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
