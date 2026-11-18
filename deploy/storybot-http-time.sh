#!/bin/bash
# Set the clock from an HTTP "Date" header when NTP cannot sync: the school
# network blocks UDP 123, and without an RTC battery the Jetson boots in 1970,
# which breaks TLS (git pull, OTA update checks).
# shortcut: ~1 s precision and an unauthenticated header (a LAN attacker could
# skew the clock); fine for a kiosk, move to chrony+NTS if that ever matters.

[ "$(timedatectl show -p NTPSynchronized --value)" = yes ] && exit 0

# Retry for ~2 min: right after boot the first requests time out even with
# WiFi up, and the timer's next run is 15 min away.
for attempt in 1 2 3 4 5 6; do
    for url in http://www.google.com http://www.cloudflare.com http://www.microsoft.com; do
        header=$(curl -sSI --max-time 5 "$url" 2>/tmp/storybot-http-time.err | sed -n 's/^[Dd]ate: //p' | tr -d '\r')
        [ -n "$header" ] || continue
        new=$(date -d "$header" +%s 2>/dev/null) || continue
        now=$(date +%s)
        diff=$(( new > now ? new - now : now - new ))
        [ "$diff" -lt 5 ] && exit 0
        date -s "@$new" >/dev/null
        hwclock -w 2>/dev/null || true
        logger -t storybot-http-time "clock stepped by ${diff}s using $url (attempt $attempt)"
        exit 0
    done
    logger -t storybot-http-time "attempt $attempt failed: $(head -c 200 /tmp/storybot-http-time.err)"
    sleep 10
done
# Offline is the normal kiosk state: not a failure, the timer retries later.
exit 0
