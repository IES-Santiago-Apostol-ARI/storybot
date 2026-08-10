#!/usr/bin/env bash
# Install the immediate-poweroff handler for the hardware power button.
#
# Two halves, both required:
#   1. dconf system default (locked) turning off GNOME's interactive
#      end-session dialog, which otherwise answers a press with
#      Cancel / Power Off and a 60 second countdown.
#   2. storybot-powerkey.service, which reads the evdev node directly and
#      powers off on the press edge.
#
# Idempotent: safe to re-run. Called by install.sh, or standalone with sudo.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $EUID -ne 0 ]]; then
    echo "This script must run as root (use sudo)." >&2
    exit 1
fi

# --- 1. Suppress the GNOME power-key dialog for every user -------------------
# A system-db entry rather than a per-user gsettings call: it applies before
# anyone logs in, survives new users, and needs no D-Bus session.
#
# Skipped when dconf-cli is absent: a stories-only box has no GNOME, so there is
# no dialog to suppress -- and since install.sh runs under `set -e`, an
# unguarded failure here would abort the whole install before step 2 lands.
if command -v dconf > /dev/null; then
    if [[ ! -f /etc/dconf/profile/user ]]; then
        printf 'user-db:user\nsystem-db:local\n' > /etc/dconf/profile/user
    elif ! grep -q '^system-db:local$' /etc/dconf/profile/user; then
        printf 'system-db:local\n' >> /etc/dconf/profile/user
    fi

    mkdir -p /etc/dconf/db/local.d/locks
    cp "$SCRIPT_DIR/dconf-storybot-powerkey" \
        /etc/dconf/db/local.d/00-storybot-powerkey

    # Locked, so a stray per-user value cannot bring the dialog back on a kiosk
    # that has no keyboard to dismiss it with.
    cat > /etc/dconf/db/local.d/locks/00-storybot-powerkey << 'EOF'
/org/gnome/settings-daemon/plugins/power/power-button-action
EOF

    dconf update
else
    echo "dconf not found -- skipping GNOME power-dialog override (no desktop)."
fi

# --- 2. Install the evdev handler -------------------------------------------
install -m 0755 "$SCRIPT_DIR/storybot-powerkey.py" /usr/local/bin/storybot-powerkey.py
install -m 0644 "$SCRIPT_DIR/storybot-powerkey.service" \
    /etc/systemd/system/storybot-powerkey.service

systemctl daemon-reload
systemctl enable --now storybot-powerkey.service

echo "Power button configured for immediate poweroff."
