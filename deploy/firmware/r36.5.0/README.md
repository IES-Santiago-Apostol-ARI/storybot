# Pre-built NVMe cold-boot fix artifacts — L4T R36.5.0 (JetPack 6.2)

Pre-built outputs of `deploy/jetson-orin-nano-nvme-cold-boot-fix.md`, archived
so provisioning another Jetson does NOT require re-downloading the BSP or
redoing the Docker EDK2 build (Parts 1.1–1.4 and 2.1–2.5 of that doc).

**Only valid for L4T R36.5.0.** For any other release, rebuild following the
doc (the `.patch` here applies the source changes).

| File | What it is |
|------|------------|
| `uefi_t23x_general_RELEASE.bin` | Patched UEFI firmware (PCIe post-PERST# delay 200ms→5000ms + 20×500ms link-up retry loop). Output of doc steps 2.1–2.5. Verified: this exact binary (md5 `5ac2859b36ab6b4fa0d3647615e77bc4`) was flashed 2026-07-13 and fixed the cold boot. |
| `L4TConfiguration.dtbo` | Modified L4T configuration: `DefaultBootPriority = "nvme"` (no PXE/HTTP entries) + 15 s UEFI timeout. Output of doc steps 1.2–1.4. |
| `L4TConfiguration.dts` | Decompiled source of the `.dtbo`, for reference/re-editing. |
| `pcie-cold-boot-fix.patch` | The clean source diff against `edk2-nvidia` tag `r36.5` (commit `79ad0c17`), to reproduce the UEFI build on future releases: `git apply pcie-cold-boot-fix.patch` inside `edk2-nvidia/`. |
| `SHA256SUMS` | Checksums — verify with `sha256sum -c SHA256SUMS`. |

Build provenance: edk2-nvidia `r36.5` / `uefi-202504.2` (79ad0c17), build id
`r36.5-79ad0c17-dirty`, built 2026-07-13 in the tianocore ubuntu-22 Docker
container per the doc.

## How to use on a new Jetson (Route A — capsule, no recovery mode)

You still need the R36.5.0 BSP (`Linux_for_Tegra/`, kept at
`/datos/Linux_for_Tegra` on the dev machine) to *package* the capsule — but
nothing needs to be rebuilt. On the host PC:

```bash
sudo bash deploy/generate-patched-capsule.sh [path-to-Linux_for_Tegra]
# verifies SHA256SUMS, copies these artifacts into the BSP, runs NVIDIA's
# BUP + capsule generation; output: deploy/firmware/r36.5.0/TEGRA_BL_patched.Cap
```

Then on the Jetson (after `install.sh` + reboot so the super DTB is booted):

```bash
sudo bash deploy/enable-super-firmware.sh /path/to/TEGRA_BL_patched.Cap
sudo reboot    # progress bar 1-5 min — DO NOT POWER OFF
sudo apt-mark hold nvidia-l4t-bootloader
```

The script leaves `TEGRA_BL_patched.Cap` in this directory. **It is not
committed and cannot be**: the multi-spec capsule is ~128 MB, over GitHub's
100 MB hard limit, so `deploy/firmware/**/*.Cap` is gitignored. The artifacts
in this directory are the committed source of truth — regenerate the capsule
from them when needed.

## Recovery flash (Route B — rescue only)

The same two `cp` commands above, then the recovery-mode `flash.sh -k
A_cpu-bootloader` / `-k B_cpu-bootloader` invocations from doc sections
1.5/2.6.
