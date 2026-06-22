# Plan 34-01 Summary: LED-26 Install-Automation Logic Tests (RED)

## Status
COMPLETE — RED phase only. Tests committed, all fail as expected.

## What Was Done
Created `tests/test_deploy/test_spi_install.py` with 12 source-assertion tests against `deploy/install.sh` that validate the SPI1-enable install-automation logic required by LED-26:

| # | Test | Assertion | Status |
|---|------|-----------|--------|
| 1 | `test_udev_rule_content_present` | udev rule uses `GROUP="spi"` and `MODE="0660"` (least-privilege) | RED |
| 2 | `test_udev_rule_file_path` | Rule written to `/etc/udev/rules.d/99-storybot-spi.rules` | RED |
| 3 | `test_groupadd_spi_present` | `groupadd -f spi` is present | RED |
| 4 | `test_usermod_spi_present` | `usermod -aG spi "$INSTALL_USER"` is present | RED |
| 5 | `test_wrong_tool_not_used_for_spi1` | `config-by-hardware.py` must NOT appear | GREEN (negative) |
| 6 | `test_config_by_function_used` | `config-by-function.py` is used for SPI1 enablement | RED |
| 7 | `test_config_by_function_spi1_option` | `-o dt spi1` invocation is present | RED |
| 8 | `test_idempotency_guard_present` | `[ -e /dev/spidev0.0 ]` skip-if-exists guard | RED |
| 9 | `test_fail_soft_manual_instructions` | Manual `jetson-io.py` instructions in error branch | RED |
| 10 | `test_fail_soft_no_exit_in_manual_branch` | Fail-soft branch must NOT contain `exit` | RED |
| 11 | `test_reboot_prompt_present` | `REBOOT` message surfaced to operator | RED |
| 12 | `test_spi_step_before_systemd_service` | SPI1 step appears BEFORE "Step 6: Install systemd service" | RED |

## Key Decisions
- Used `config-by-function.py -o dt spi1` as the correct tool (not `config-by-hardware.py -n 2='spi1'`) per RESEARCH.md Pitfall 1 correction
- Applied least-privilege udev rule: GROUP="spi" MODE="0660" (not 0666/plugdev) per D-02
- Negative assertion test for wrong tool (`config-by-hardware.py` must NOT appear) — already passes because tool isn't in install.sh yet
- Followed existing deploy-test analogs: `test_bt_boot_unit.py` and `test_install_script.py` for structure and idiom

## Verification
```bash
uv run pytest tests/test_deploy/test_spi_install.py -v  # 11 RED, 1 GREEN (negative)
uv run pytest tests/test_deploy/ -q                     # No regression in existing tests
```
