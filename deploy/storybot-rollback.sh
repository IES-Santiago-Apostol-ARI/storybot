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

WORK_DIR="/home/ari/storybot"
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

    # Perform rollback in a subshell — errors are logged but do not
    # prevent the service from starting (which may already be running
    # the old code after a manual fix)
    (
        set -e
        cd "$WORK_DIR"
        git reset --hard "$PREV_HASH"
        "$WORK_DIR/.venv/bin/uv" sync
    ) || true

    exit 0
fi

# Unknown state — remove flag and continue
rm -f "$FLAG"
exit 0
