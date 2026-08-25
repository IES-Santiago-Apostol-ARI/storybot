#!/bin/bash
#
# StoryBot OTA Rollback Check Script
#
# Implements the two-state flag rollback mechanism (D-13).
# Run as ExecStartPre by systemd before every service start.
#
# The script reads .update-state JSON from the service WorkingDirectory.
# Three states:
#   1. No file exists: normal boot, do nothing (exit 0)
#   2. state="pending": first start after OTA update, mark as "attempted" (exit 0)
#   3. state="attempted": previous start failed, rollback via git reset (exit 0)
#
# This script MUST always exit 0. A non-zero exit code prevents systemd
# from starting the service.
#

# __INSTALL_DIR__ is substituted by deploy/install.sh (from INSTALL_USER in
# .env) when this script is installed to /usr/local/bin.
WORK_DIR="__INSTALL_DIR__"
FLAG="$WORK_DIR/.update-state"

# State 1: No flag file — normal boot, nothing to do
if [[ ! -f "$FLAG" ]]; then
    exit 0
fi

# Read current state from JSON flag file
STATE=$(python3 -c "
import json, sys
try:
    with open('$FLAG') as f:
        data = json.load(f)
    print(data.get('state', ''))
except Exception:
    print('')
" 2>/dev/null)

# If state is empty (malformed JSON or missing key), remove flag and continue
if [[ -z "$STATE" ]]; then
    rm -f "$FLAG"
    exit 0
fi

if [[ "$STATE" == "pending" ]]; then
    # State 2: Update was applied, this is the first start attempt.
    # Mark as "attempted" so that if the service crashes, the next start
    # will trigger a rollback.
    python3 -c "
import json
with open('$FLAG') as f:
    data = json.load(f)
data['state'] = 'attempted'
with open('$FLAG', 'w') as f:
    json.dump(data, f)
" 2>/dev/null
    exit 0
fi

if [[ "$STATE" == "attempted" ]]; then
    # State 3: Previous start failed — rollback to previous commit
    PREV_HASH=$(python3 -c "
import json, sys
try:
    with open('$FLAG') as f:
        data = json.load(f)
    print(data.get('prev_hash', ''))
except Exception:
    print('')
" 2>/dev/null)

    # Remove flag first to prevent rollback loops on subsequent starts
    rm -f "$FLAG"

    if [[ -z "$PREV_HASH" ]]; then
        exit 0
    fi

    # Resolve uv: systemd's PATH does not include ~/.local/bin, where
    # install.sh puts it, and there is no uv inside the venv.
    UV_BIN="$(command -v uv 2>/dev/null || true)"
    if [[ -z "$UV_BIN" ]]; then
        for candidate in "$HOME/.local/bin/uv" "$WORK_DIR/.venv/bin/uv"; do
            if [[ -x "$candidate" ]]; then
                UV_BIN="$candidate"
                break
            fi
        done
    fi

    # Perform rollback in a subshell — errors are logged but do not
    # prevent the service from starting (which may already be running
    # the old code after a manual fix)
    (
        set -e
        cd "$WORK_DIR"
        git reset --hard "$PREV_HASH"
        if [[ -n "$UV_BIN" ]]; then
            "$UV_BIN" sync
            # uv sync prunes the system Jetson.GPIO symlink install.sh made
            # (it lives in the `jetson` extra, skipped on aarch64). Without
            # it the GPIO buttons fall back to the Mock. Mirror install.sh.
            if [[ "$(uname -m)" == "aarch64" ]]; then
                SYS_JETSON="/usr/lib/python3/dist-packages/Jetson"
                VENV_SITE="$WORK_DIR/.venv/lib/python3.10/site-packages"
                if [[ -d "$SYS_JETSON" && -d "$VENV_SITE" ]]; then
                    ln -sfn "$SYS_JETSON" "$VENV_SITE/Jetson"
                    for egg in /usr/lib/python3/dist-packages/Jetson.GPIO-*.egg-info; do
                        [[ -e "$egg" ]] && ln -sfn "$egg" "$VENV_SITE/$(basename "$egg")"
                    done
                fi
            fi
        else
            echo "storybot-rollback: uv not found, dependencies not synced" >&2
        fi
    ) || true

    exit 0
fi

# Unknown state — remove flag and continue
rm -f "$FLAG"
exit 0
