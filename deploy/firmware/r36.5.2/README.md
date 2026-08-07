# Pre-built NVMe cold-boot fix artifacts — L4T R36.5.2 (JetPack 6.2.3)

Pre-built outputs of `deploy/jetson-orin-nano-nvme-cold-boot-fix.md`, archived
so provisioning another Jetson does NOT require re-downloading the BSP or
redoing the Docker EDK2 build (Parts 1.1–1.4 and 2.1–2.5 of that doc).

Built 2026-08-07 to restore the fix after the 2026-08-06 `apt dist-upgrade`
reverted it (doc Part 3.5, regression log).

## The directory name is the BSP release, not the UEFI source tag

These two artifacts are versioned by different things — read this before
assuming a same-named rebuild exists for some future release:

- `L4TConfiguration.dtbo` **is** BSP-coupled. It is derived from the R36.5.2
  BSP's own `kernel/dtb/L4TConfiguration.dtbo` and is only valid for R36.5.2.
- `uefi_t23x_general_RELEASE.bin` is **not** BSP-coupled. It is built purely
  from the edk2 git repos; the BSP is never read. It is built here from
  **`r36.5.1`**, the newest published UEFI source tag — NVIDIA never released
  UEFI source for R36.5.2, so `r36.5.1` is as current as this binary can be.

Consequence: this UEFI does not carry the R36.5.2 UEFI fix 5412830
(StandaloneMM variable storage). That fix is not in public source and cannot
be built. The R36.5.2 kernel and userspace fixes are unaffected.

| File | What it is |
|------|------------|
| `uefi_t23x_general_RELEASE.bin` | Patched UEFI firmware (PCIe post-PERST# delay 200ms→5000ms + 20×500ms link-up retry loop). Output of doc steps 2.1–2.5, built from edk2-nvidia `r36.5.1`. md5 `c49ae9f0f6b9a2a1ac935aa55feaee2f`. |
| `L4TConfiguration.dtbo` | Modified L4T configuration: `DefaultBootPriority = "nvme"` (no PXE/HTTP entries) + 15 s UEFI timeout. Output of doc steps 1.2–1.4 against the **R36.5.2** BSP. |
| `L4TConfiguration.dts` | Decompiled source of the `.dtbo`, for reference/re-editing. |
| `pcie-cold-boot-fix.patch` | The source diff, identical to the R36.5.0 archive's copy — `PcieControllerDxe.c` is unchanged upstream since 2024-10-31 (blob `222275dc` at `r36.5`, `r36.5.1` and `r36.5-updates`). Apply inside `edk2-nvidia/` with `git apply -p1 --ignore-whitespace` — **the flag is required**, the source file is CRLF and this patch is LF. |
| `SHA256SUMS` | Checksums — verify with `sha256sum -c SHA256SUMS`. |

Build provenance: edk2-nvidia `r36.5.1` (`3dfabbec`), build id
`r36.5.1-3dfabbec-dirty` (`-dirty` = the PCIe patch above), built 2026-08-07
in the tianocore ubuntu-22 Docker container per the doc.

> **Verified on-device 2026-08-07.** The capsule installed cleanly (slot
> flipped A→B, capsule consumed from the ESP), `bios_version` reports
> `r36.5.1-3dfabbec-dirty` (this exact build), `Timeout: 15 seconds` restored,
> Super profile intact (25W, EMC 3199000000) — and the **cold boot passes**:
> powered off, ~30 s unplugged, powered on, booted straight from
> `/dev/nvme0n1p1` with no drop to the UEFI shell.
>
> Fallback if ever needed: `deploy/firmware/r36.5.0/uefi_t23x_general_RELEASE.bin`
> (md5 `5ac2859b36ab6b4fa0d3647615e77bc4`), an `r36.5`-source build differing
> only by the DisplayDeviceTreeHelperLib commit.

## How to use (Route A — capsule, no recovery mode)

You still need the R36.5.2 BSP (`Linux_for_Tegra/`, kept at
`/datos/Linux_for_Tegra` on the dev machine) to *package* the capsule — but
nothing needs to be rebuilt. On the host PC:

```bash
sudo bash deploy/generate-patched-capsule.sh [path-to-Linux_for_Tegra]
# reads the release from the BSP's nv_tegra/bsp_version, verifies SHA256SUMS,
# copies these artifacts into the BSP, runs NVIDIA's BUP + capsule generation;
# output: deploy/firmware/r36.5.2/TEGRA_BL_patched.Cap
```

Then on the Jetson (after `install.sh` + reboot so the super DTB is booted):

```bash
sudo bash deploy/enable-super-firmware.sh /path/to/TEGRA_BL_patched.Cap
sudo reboot    # progress bar 1-5 min — DO NOT POWER OFF
sudo apt-mark hold nvidia-l4t-bootloader
apt-mark showhold    # MUST list nvidia-l4t-bootloader — this is the step
                     # that silently failed and caused the 2026-08 regression
```

The script leaves `TEGRA_BL_patched.Cap` in this directory. **It is not
committed and cannot be**: the multi-spec capsule is ~128 MB, over GitHub's
100 MB hard limit, so `deploy/firmware/**/*.Cap` is in `.gitignore`. The
artifacts in this directory are the committed source of truth — regenerate
the capsule from them with one command whenever it is needed. Keep a copy
outside the repo if you want to provision a device without the BSP tree.

## Recovery flash (Route B — rescue only)

The same two `cp` commands the script performs, then the recovery-mode
`flash.sh -k A_cpu-bootloader` / `-k B_cpu-bootloader` invocations from doc
sections 1.5/2.6.
