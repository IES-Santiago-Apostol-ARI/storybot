#!/usr/bin/env bash
# Phase 16 D-15/D-17: sample VmRSS of the three relevant processes every 2s.
# Run on the Jetson during the 10-iteration soak. Output: /tmp/rss-soak.log
# Usage:
#   bash scripts/jetson_rss_sampler.sh | tee /tmp/rss-soak.log
# Stop with Ctrl-C after the soak completes.

set -u

while true; do
    ts=$(date +%s)
    echo "--- ts=$ts ---"
    for proc in llama-server uvicorn sd_cover_worker; do
        for pid in $(pgrep -f "$proc" 2>/dev/null); do
            rss=$(awk '/^VmRSS:/ {print $2}' "/proc/$pid/status" 2>/dev/null)
            if [ -n "${rss:-}" ]; then
                printf "%s pid=%s VmRSS_kB=%s\n" "$proc" "$pid" "$rss"
            fi
        done
    done
    sleep 2
done
