#!/bin/bash
#
# StoryBot Installation Script
#
# This script sets up a complete StoryBot deployment on any Linux device.
# It auto-detects AI capability (NVIDIA GPU) and adapts the installation.
#
# The service account that owns the install is NOT hardcoded: it is read from
# the INSTALL_USER variable in the project's .env file. Create .env (see
# .env.example) with at least `INSTALL_USER=<user>` before running this script.
# The project can be cloned anywhere owned by that user; the installer resolves
# its location from this script's path.
#
# Usage:
#   sudo bash deploy/install.sh [--dev] [--ai|--no-ai]
#
# Options:
#   --dev      Skip model downloads (for development/testing)
#   --ai       Force AI mode (LLM + TTS + SD covers)
#   --no-ai    Force stories-only mode (no AI services)
#
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Resolve the repo location from this script's path so the installer works
# regardless of where the project was cloned.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$INSTALL_DIR/.env"

# INSTALL_USER is the service account that owns the install. It is read from
# .env (never hardcoded). Strip surrounding quotes and whitespace.
INSTALL_USER="$(grep -E '^INSTALL_USER=' "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2-)"
INSTALL_USER="${INSTALL_USER//\"/}"
INSTALL_USER="${INSTALL_USER//\'/}"
INSTALL_USER="$(echo -n "$INSTALL_USER" | xargs)"

DEV_MODE=false
AI_FLAG=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dev)
            DEV_MODE=true
            shift
            ;;
        --ai)
            AI_FLAG="force-on"
            shift
            ;;
        --no-ai)
            AI_FLAG="force-off"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}ERROR: This script must be run as root${NC}"
   echo "Use: sudo bash deploy/install.sh"
   exit 1
fi

# INSTALL_USER must be defined in .env before running the installer.
if [[ -z "$INSTALL_USER" ]]; then
    echo -e "${RED}ERROR: INSTALL_USER is not set in $ENV_FILE${NC}"
    echo "Add a line like 'INSTALL_USER=ari' to .env (see .env.example) and re-run."
    exit 1
fi

# Resolve the user's home directory (used for uv, autostart, TTS models, etc.)
USER_HOME="$(getent passwd "$INSTALL_USER" | cut -d: -f6)"
if [[ -z "$USER_HOME" ]]; then
    echo -e "${RED}ERROR: system user '$INSTALL_USER' (from .env) does not exist${NC}"
    exit 1
fi

# Detect AI capability
if [[ "$AI_FLAG" == "force-on" ]]; then
    AI_MODE=true
elif [[ "$AI_FLAG" == "force-off" ]]; then
    AI_MODE=false
else
    # Auto-detect: probe for NVIDIA GPU
    if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
        AI_MODE=true
    elif ls /dev/nvidia* &>/dev/null 2>&1; then
        AI_MODE=true
    else
        AI_MODE=false
    fi
fi

echo "================================================"
echo "StoryBot Installation Script"
echo "================================================"
echo "Target directory: $INSTALL_DIR"
echo "Service user: $INSTALL_USER"
echo "Dev mode: $DEV_MODE"
echo "AI mode: $AI_MODE"
echo ""

# Write AI mode to .env file, preserving INSTALL_USER (and any other vars).
if [[ "$AI_MODE" == true ]]; then
    AI_VALUE=1
else
    AI_VALUE=0
fi
if grep -qE '^STORYBOT_AI=' "$ENV_FILE"; then
    sed -i "s/^STORYBOT_AI=.*/STORYBOT_AI=$AI_VALUE/" "$ENV_FILE"
else
    echo "STORYBOT_AI=$AI_VALUE" >> "$ENV_FILE"
fi
chown "$INSTALL_USER:$INSTALL_USER" "$ENV_FILE"

# Step 1: Install system dependencies
echo ""
echo "Step 1: Installing system dependencies..."
apt-get update
apt-get install -y nginx unclutter pcscd pcsc-tools libccid libpcsclite-dev swig uhubctl avahi-daemon avahi-utils

# AI-specific: NVIDIA JetPack (GPU drivers + CUDA + TensorRT + cuDNN)
if [[ "$AI_MODE" == true ]]; then
    apt-get install -y nvidia-jetpack
else
    echo -e "${YELLOW}Skipping nvidia-jetpack (stories-only mode)${NC}"
fi
# audio bluetooth:
apt-get -y  install pipewire pipewire-pulse wireplumber libspa-0.2-bluetooth bluez bluez-tools cmake libasound2-dev

# Audio: configure pipewire in the install user's session, not root's.
# `systemctl --user` needs the target user's DBus session — run via sudo -u
# with XDG_RUNTIME_DIR/DBUS_SESSION_BUS_ADDRESS exported. Skip silently if
# the user has no active session (e.g. headless first-boot install).
USER_UID=$(id -u "$INSTALL_USER")
if [[ -d "/run/user/$USER_UID" ]]; then
    sudo -u "$INSTALL_USER" \
        XDG_RUNTIME_DIR="/run/user/$USER_UID" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_UID/bus" \
        systemctl --user mask pulseaudio || true
    sudo -u "$INSTALL_USER" \
        XDG_RUNTIME_DIR="/run/user/$USER_UID" \
        pulseaudio -k 2>/dev/null || true
    sudo -u "$INSTALL_USER" \
        XDG_RUNTIME_DIR="/run/user/$USER_UID" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_UID/bus" \
        systemctl --user --now enable pipewire pipewire-pulse wireplumber || true
else
    echo -e "${YELLOW}No active user session for $INSTALL_USER — skipping pipewire user-unit setup${NC}"
fi

echo -e "${GREEN}System dependencies installed${NC}"

# Enable pcscd socket (PC/SC daemon for NFC reader)
systemctl enable --now pcscd.socket
systemctl enable --now pcscd
echo -e "${GREEN}pcscd enabled${NC}"

# Blacklist kernel NFC modules that conflict with pcscd/CCID access to ACR122U
cat > /etc/modprobe.d/storybot-nfc.conf << 'EOF'
# Prevent Linux NFC kernel drivers from grabbing the ACR122U before pcscd can claim it
blacklist pn533_usb
blacklist pn533
blacklist nfc
EOF
modprobe -r pn533_usb pn533 nfc 2>/dev/null || true
echo -e "${GREEN}Kernel NFC modules blacklisted${NC}"

# Step 2: Install Python dependencies
echo ""
echo "Step 2: Installing Python dependencies..."
cd "$INSTALL_DIR"

# Check for uv
if ! sudo -u "$INSTALL_USER" bash -c 'command -v uv' &>/dev/null; then
    echo "Installing uv package manager..."
    sudo -u "$INSTALL_USER" bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
fi

# Create virtualenv (idempotent - skips if exists)
echo "Creating virtual environment..."
if [[ ! -d "$INSTALL_DIR/.venv" ]]; then
    sudo -u "$INSTALL_USER" "$USER_HOME/.local/bin/uv" venv "$INSTALL_DIR/.venv"
else
    echo "Virtual environment already exists, skipping..."
fi

# Install dependencies.
# On the real Jetson (aarch64), CUDA/TensorRT/cuDNN come from system apt
# (nvidia-jetpack) - never pip-install them, so always use a plain sync there.
# On an x86 box in AI mode, pull the jetson extra to emulate the AI stack.
echo "Installing Python packages..."
if [[ "$AI_MODE" == true && "$(uname -m)" != "aarch64" ]]; then
    echo "AI mode on x86 - installing jetson extra (dev emulation)..."
    sudo -u "$INSTALL_USER" "$USER_HOME/.local/bin/uv" sync --extra jetson
else
    sudo -u "$INSTALL_USER" "$USER_HOME/.local/bin/uv" sync
fi
echo -e "${GREEN}Python dependencies installed${NC}"

# Step 3: Download TTS models
if [[ "$AI_MODE" == true ]]; then
    if [[ "$DEV_MODE" == false ]]; then
        echo ""
        echo "Step 3: Downloading TTS models..."
        sudo -u "$INSTALL_USER" bash "$INSTALL_DIR/deploy/download-models.sh" "$USER_HOME/.local/share/piper"
        echo -e "${GREEN}Models downloaded${NC}"
    else
        echo ""
        echo "Step 3: Skipping model downloads (dev mode)..."
    fi
else
    echo ""
    echo "Step 3: Skipping model downloads (stories-only mode)..."
fi

# Step 4: Create content directories
echo ""
echo "Step 4: Creating content directories..."
sudo -u "$INSTALL_USER" mkdir -p "$INSTALL_DIR/content/stories"
sudo -u "$INSTALL_USER" mkdir -p "$INSTALL_DIR/content/interactive"
sudo -u "$INSTALL_USER" mkdir -p "$INSTALL_DIR/content/images"
echo -e "${GREEN}Content directories created${NC}"

# Step 5: Configure hardware permissions
echo ""
echo "Step 5: Configuring hardware permissions..."

# Add user to required groups
usermod -aG audio "$INSTALL_USER"
usermod -aG dialout "$INSTALL_USER"
usermod -aG plugdev "$INSTALL_USER" || true
echo -e "${GREEN}Added $INSTALL_USER to audio, dialout, plugdev groups${NC}"

# No custom udev rule needed for ACR122U — pcscd manages it via CCID

# Create udev rules for Brother printer
cat > /etc/udev/rules.d/99-storybot-printer.rules << 'EOF'
# Brother QL series printers
SUBSYSTEM=="usb", ATTR{idVendor}=="04f9", MODE="0666", GROUP="plugdev"
EOF
echo -e "${GREEN}Created udev rules for printer${NC}"

# Reload udev rules
udevadm control --reload-rules
udevadm trigger
udevadm settle

# Step 6: Install systemd service
echo ""
echo "Step 6: Installing systemd service..."
# storybot.service and storybot-rollback.sh are templates: substitute the
# install user and directory before installing them.
sed -e "s|__INSTALL_USER__|$INSTALL_USER|g" -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
    "$INSTALL_DIR/deploy/storybot.service" > /etc/systemd/system/storybot.service
cp "$INSTALL_DIR/deploy/storybot-nfc-reset.service" /etc/systemd/system/
cp "$INSTALL_DIR/deploy/storybot-reset-nfc.sh" /usr/local/bin/storybot-reset-nfc.sh
chmod +x /usr/local/bin/storybot-reset-nfc.sh
sed -e "s|__INSTALL_DIR__|$INSTALL_DIR|g" \
    "$INSTALL_DIR/deploy/storybot-rollback.sh" > /usr/local/bin/storybot-rollback.sh
chmod +x /usr/local/bin/storybot-rollback.sh
systemctl daemon-reload
systemctl enable storybot.service
systemctl enable storybot-nfc-reset.service
echo -e "${GREEN}Systemd service installed${NC}"

# Step 6b: Configure passwordless sudo for llama-server control
# The storybot service runs as $INSTALL_USER and must stop/start llama-server
# during the SD cover swap cycle. Grant NOPASSWD for just those two commands.
echo ""
if [[ "$AI_MODE" == true ]]; then
    echo "Step 6b: Configuring passwordless sudo for llama-server control..."
    cat > /etc/sudoers.d/storybot-llama << EOF
${INSTALL_USER} ALL=(root) NOPASSWD: /bin/systemctl stop llama-server, /bin/systemctl start llama-server
EOF
    chmod 0440 /etc/sudoers.d/storybot-llama
    visudo -c -f /etc/sudoers.d/storybot-llama
    echo -e "${GREEN}Sudoers entry installed${NC}"
else
    echo "Step 6b: Skipping llama-server sudoers (stories-only mode)..."
fi

# Step 6c: Deploy polkit rule for passwordless WiFi management
echo ""
echo "Step 6c: Deploying polkit rule for WiFi management..."
mkdir -p /etc/polkit-1/localauthority/50-local.d
cat > /etc/polkit-1/localauthority/50-local.d/10-storybot-wifi.pkla << EOF
[StoryBot WiFi Management]
Identity=unix-user:${INSTALL_USER}
Action=org.freedesktop.NetworkManager.wifi.scan;org.freedesktop.NetworkManager.enable-disable-wifi;org.freedesktop.NetworkManager.settings.modify.own;org.freedesktop.NetworkManager.settings.modify.system;org.freedesktop.NetworkManager.network-control
ResultAny=yes
ResultInactive=yes
ResultActive=yes
EOF
chmod 0644 /etc/polkit-1/localauthority/50-local.d/10-storybot-wifi.pkla
echo -e "${GREEN}Polkit WiFi rule installed${NC}"

# Step 6d: Configure Ethernet never-default (prevents WiFi routing breakage)
echo ""
echo "Step 6d: Configuring Ethernet never-default..."
# Topology: Ethernet -> TP-Link AP (local kiosk LAN, NO internet);
#           WiFi      -> upstream router (internet, used for OTA updates).
# For internet via WiFi to survive Ethernet being plugged in, three things
# must hold on EVERY Ethernet profile (not just the one active right now):
#   1. never-default  -> Ethernet never installs a default route.
#   2. route-metric    -> if it ever does, WiFi (metric 600) still wins.
#   3. DNS de-priority -> the TP-Link's DNS (no internet) must not be queried
#      first, otherwise lookups fail even when routing is correct.
ETH_IFACE=""
mapfile -t ETH_CONNS < <(nmcli -t -f NAME,TYPE connection show | grep ':802-3-ethernet$' | cut -d: -f1)
if [[ ${#ETH_CONNS[@]} -gt 0 ]]; then
    for ETH_CONN in "${ETH_CONNS[@]}"; do
        nmcli connection modify "$ETH_CONN" \
            ipv4.never-default yes ipv6.never-default yes \
            ipv4.route-metric 700 ipv6.route-metric 700 \
            ipv4.dns-priority 200 ipv6.dns-priority 200 \
            ipv4.ignore-auto-dns yes ipv6.ignore-auto-dns yes
        echo -e "${GREEN}Ethernet routing/DNS de-prioritised for '$ETH_CONN'${NC}"
    done
    # Re-apply on the active Ethernet connection so it takes effect now
    # rather than only after the next reboot.
    ACTIVE_ETH=$(nmcli -t -f NAME,TYPE connection show --active | grep ':802-3-ethernet$' | cut -d: -f1)
    if [[ -n "$ACTIVE_ETH" ]]; then
        ETH_IFACE=$(nmcli -t -f GENERAL.DEVICES connection show "$ACTIVE_ETH" | cut -d: -f2)
        nmcli connection up "$ACTIVE_ETH" >/dev/null 2>&1 || true
    fi
else
    echo -e "${YELLOW}No Ethernet connection profile found -- skipping never-default${NC}"
fi

# Loosen reverse-path filtering so replies on the WiFi interface aren't
# dropped just because the routing table prefers the Ethernet link for
# the matching subnet (classic dual-interface "WiFi internet stops
# working when Ethernet is plugged in" issue).
cat > /etc/sysctl.d/99-storybot-routing.conf << 'EOF'
net.ipv4.conf.all.rp_filter=2
net.ipv4.conf.default.rp_filter=2
EOF
sysctl --system >/dev/null
echo -e "${GREEN}Loose reverse-path filtering configured${NC}"

# Step 6e: Configure passwordless sudo for service restart (OTA updates)
echo ""
echo "Step 6e: Configuring passwordless sudo for OTA service restart..."
cat > /etc/sudoers.d/storybot-updates << EOF
${INSTALL_USER} ALL=(root) NOPASSWD: /bin/systemctl restart storybot
EOF
chmod 0440 /etc/sudoers.d/storybot-updates
visudo -c -f /etc/sudoers.d/storybot-updates
echo -e "${GREEN}Sudoers entry for OTA updates installed${NC}"

# Step 6f: Configure Avahi (mDNS) so devices on the TP-Link AP can reach
# the device as storybot.local without knowing its IP address.
echo ""
echo "Step 6f: Configuring Avahi mDNS announcement..."
if grep -q "^#host-name=" /etc/avahi/avahi-daemon.conf; then
    sed -i "s/^#host-name=.*/host-name=storybot/" /etc/avahi/avahi-daemon.conf
elif ! grep -q "^host-name=" /etc/avahi/avahi-daemon.conf; then
    sed -i "/^\[server\]/a host-name=storybot" /etc/avahi/avahi-daemon.conf
fi
if [[ -n "$ETH_IFACE" ]]; then
    if grep -q "^#allow-interfaces=" /etc/avahi/avahi-daemon.conf; then
        sed -i "s/^#allow-interfaces=.*/allow-interfaces=$ETH_IFACE/" /etc/avahi/avahi-daemon.conf
    elif grep -q "^allow-interfaces=" /etc/avahi/avahi-daemon.conf; then
        sed -i "s/^allow-interfaces=.*/allow-interfaces=$ETH_IFACE/" /etc/avahi/avahi-daemon.conf
    else
        sed -i "/^\[server\]/a allow-interfaces=$ETH_IFACE" /etc/avahi/avahi-daemon.conf
    fi
    echo -e "${GREEN}Avahi restricted to interface '$ETH_IFACE'${NC}"
else
    echo -e "${YELLOW}No Ethernet interface detected -- Avahi will announce on all interfaces${NC}"
fi

cat > /etc/avahi/services/storybot.service << 'EOF'
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">StoryBot on %h</name>
  <service>
    <type>_http._tcp</type>
    <port>80</port>
  </service>
</service-group>
EOF

systemctl enable --now avahi-daemon
systemctl restart avahi-daemon
echo -e "${GREEN}Avahi configured -- device reachable at http://storybot.local${NC}"

# Step 7: Configure Nginx reverse proxy
echo ""
echo "Step 7: Configuring Nginx reverse proxy..."
cp "$INSTALL_DIR/deploy/storybot-nginx.conf" /etc/nginx/sites-available/storybot
ln -sf /etc/nginx/sites-available/storybot /etc/nginx/sites-enabled/storybot
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx
systemctl restart nginx
echo -e "${GREEN}Nginx configured${NC}"

# Step 8: Configure GDM3 autologin (AI/kiosk devices only)
echo ""
if [[ "$AI_MODE" == true ]]; then
    echo "Step 8: Configuring GDM3 autologin..."
    cat > /etc/gdm3/custom.conf << GDMEOF
[daemon]
AutomaticLoginEnable=true
AutomaticLogin=$INSTALL_USER

[security]

[xdmcp]

[chooser]

[debug]
GDMEOF
    echo -e "${GREEN}GDM3 autologin configured${NC}"
else
    echo "Step 8: Skipping GDM3 autologin (stories-only mode)..."
fi

# Step 9: Configure GNOME autostart (Firefox kiosk + unclutter) — AI/kiosk only
echo ""
if [[ "$AI_MODE" == true ]]; then
    echo "Step 9: Configuring kiosk autostart..."
    sudo -u "$INSTALL_USER" mkdir -p "$USER_HOME/.config/autostart"

    cat > "$USER_HOME/.config/autostart/storybot-kiosk.desktop" << 'KIOSKEOF'
[Desktop Entry]
Type=Application
Name=StoryBot Kiosk
Comment=Launch Firefox kiosk for StoryBot
Exec=bash -c "unclutter -idle 0.5 & sleep 5 && MOZ_DISABLE_CONTENT_SANDBOX=1 firefox --kiosk --purgecaches --no-remote -P kiosk http://localhost/"
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
KIOSKEOF
    chown "$INSTALL_USER:$INSTALL_USER" "$USER_HOME/.config/autostart/storybot-kiosk.desktop"
    echo -e "${GREEN}Kiosk autostart configured${NC}"
else
    echo "Step 9: Skipping Firefox kiosk autostart (stories-only mode)..."
fi

# Step 10: Configure screen-never-blocks (AI/kiosk only)
echo ""
if [[ "$AI_MODE" == true ]]; then
    echo "Step 10: Configuring screen settings..."
    cat > "$USER_HOME/.config/autostart/storybot-screen-setup.desktop" << 'SCREENEOF'
[Desktop Entry]
Type=Application
Name=StoryBot Screen Setup
Comment=Disable screen blanking (runs once)
Exec=bash -c "gsettings set org.gnome.desktop.session idle-delay 0 && gsettings set org.gnome.desktop.screensaver lock-enabled false && rm -f ~/.config/autostart/storybot-screen-setup.desktop"
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
SCREENEOF
    chown "$INSTALL_USER:$INSTALL_USER" "$USER_HOME/.config/autostart/storybot-screen-setup.desktop"
    echo -e "${GREEN}Screen settings configured${NC}"
else
    echo "Step 10: Skipping screen settings (stories-only mode)..."
fi

# Step 11: Fix file ownership
echo ""
echo "Step 11: Fixing file ownership..."
chown -R "$INSTALL_USER:$INSTALL_USER" "$INSTALL_DIR"
if [[ -d "$USER_HOME/.config/autostart" ]]; then
    chown -R "$INSTALL_USER:$INSTALL_USER" "$USER_HOME/.config/autostart"
fi
echo -e "${GREEN}File ownership fixed${NC}"

# Step 12: Print TP-Link WiFi setup instructions
echo ""
echo "================================================"
echo "WiFi Access Point Setup (MANUAL)"
echo "================================================"
echo ""
echo "The TP-Link TL-WR802N must be configured manually:"
echo ""
echo "1. Connect the TP-Link to the Jetson via Ethernet"
echo "2. Connect to the TP-Link's default WiFi (see device label)"
echo "3. Open browser to http://192.168.0.1 (login: admin/admin)"
echo "4. Wireless Settings:"
echo "   - SSID: StoryBot"
echo "5. Wireless Security:"
echo "   - WPA/WPA2-Personal"
echo "   - Set a secure password"
echo "6. Network > LAN:"
echo "   - IP Address: 192.168.12.1"
echo "   - Subnet: 255.255.255.0"
echo "7. DHCP Settings:"
echo "   - Enable DHCP Server"
echo "   - IP Pool: 192.168.12.100 - 192.168.12.200"
echo "8. Reboot the AP"
echo ""
echo "After TP-Link setup, configure the Jetson's Ethernet with static IP:"
echo "  sudo nmcli connection modify \"Wired connection 1\" \\"
echo "    ipv4.method manual \\"
echo "    ipv4.addresses 192.168.12.1/24"
echo ""
echo "Teachers access the admin panel at: http://192.168.12.1/admin"
echo "Or via mDNS (no IP needed): http://storybot.local/admin"
echo ""

# Completion summary
echo ""
echo "================================================"
if [[ "$AI_MODE" == true ]]; then
    echo -e "${GREEN}Installation Complete! (Full AI Mode)${NC}"
else
    echo -e "${GREEN}Installation Complete! (Stories-Only Mode)${NC}"
fi
echo "================================================"
echo ""
echo "Installed:"
echo "  - Python dependencies (uv sync)"
echo "  - Nginx reverse proxy (port 80 -> 8000)"
echo "  - StoryBot systemd service"
echo "  - Polkit WiFi rule"
echo "  - Avahi mDNS (http://storybot.local)"
if [[ "$AI_MODE" == true ]]; then
    echo "  - NVIDIA JetPack (GPU + CUDA)"
    if [[ "$DEV_MODE" == false ]]; then
        echo "  - Piper TTS models at $USER_HOME/.local/share/piper"
    fi
    echo "  - GDM3 autologin for user $INSTALL_USER"
    echo "  - Firefox kiosk autostart"
    echo "  - Screen-never-blocks (activates on first login)"
    echo "  - Cursor hiding (unclutter)"
    echo "  - Llama-server sudoers entry"
else
    echo -e "${YELLOW}Skipped (stories-only mode):${NC}"
    echo "  - nvidia-jetpack"
    echo "  - TTS model downloads"
    echo "  - GDM3 autologin"
    echo "  - Firefox kiosk autostart"
    echo "  - Screen-never-blocks"
    echo "  - Llama-server sudoers"
    echo ""
    echo "  Access admin panel at: http://localhost/admin"
fi
echo ""
echo "To start StoryBot:"
echo "  sudo systemctl start storybot"
echo ""
echo "To check status:"
echo "  sudo systemctl status storybot"
echo "  sudo journalctl -u storybot -f"
echo ""
if [[ "$AI_MODE" == true ]]; then
    echo "After reboot:"
    echo "  - StoryBot service starts automatically (systemd)"
    echo "  - Firefox opens in kiosk mode (GNOME autostart)"
    echo "  - Screen stays on, cursor hides automatically"
else
    echo "After reboot:"
    echo "  - StoryBot service starts automatically (systemd)"
    echo "  - Access admin panel at http://localhost/admin"
fi
echo ""
