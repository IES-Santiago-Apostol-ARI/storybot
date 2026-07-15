#!/bin/bash
# Restarts the kiosk Firefox process to force a fresh page load.
# --purgecaches only clears in-memory caches on relaunch, not the on-disk
# HTTP cache (cache2), which can keep serving a stale response even after
# a code deploy. So this also wipes the on-disk caches directly. Useful
# when there's no mouse/keyboard attached to send Ctrl+Shift+R.

export DISPLAY=:0
PROFILE="$HOME/.storybot-kiosk-profile"

pkill -f "firefox.*storybot-kiosk-profile"
sleep 1

rm -rf "$PROFILE/cache2" "$PROFILE/startupCache" "$PROFILE/OfflineCache" "$PROFILE/shader-cache"

firefox --kiosk --purgecaches --no-remote -profile "$PROFILE" http://localhost/ &
disown
