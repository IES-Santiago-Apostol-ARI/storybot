#!/bin/bash
#
# StoryBot Installation Script
#
# This script sets up a complete StoryBot deployment on any Linux device.
# It auto-detects AI capability (NVIDIA GPU) and adapts the installation.
# The project should be cloned at /home/ari/storybot.
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

INSTALL_USER="ari"
INSTALL_DIR="/home/ari/storybot"
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

# Write AI mode to .env file
if [[ "$AI_MODE" == true ]]; then
    echo "STORYBOT_AI=1" > "$INSTALL_DIR/.env"
else
    echo "STORYBOT_AI=0" > "$INSTALL_DIR/.env"
fi
chown "$INSTALL_USER:$INSTALL_USER" "$INSTALL_DIR/.env"

# Step 1: Install system dependencies
echo ""
echo "Step 1: Installing system dependencies..."
apt-get update
apt-get install -y nginx unclutter pcscd pcsc-tools libccid libpcsclite-dev swig uhubctl

# AI-specific: NVIDIA JetPack (GPU drivers + CUDA + TensorRT + cuDNN)
if [[ "$AI_MODE" == true ]]; then
    apt-get install -y nvidia-jetpack
else
    echo -e "${YELLOW}Skipping nvidia-jetpack (stories-only mode)${NC}"
fi
# audio bluetooth:
apt-get -y  install pipewire pipewire-pulse wireplumber libspa-0.2-bluetooth bluez bluez-tools cmake

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
    sudo -u "$INSTALL_USER" /home/ari/.local/bin/uv venv "$INSTALL_DIR/.venv"
else
    echo "Virtual environment already exists, skipping..."
fi

# Install dependencies (no jetson extras - CUDA comes from system apt on Jetson)
echo "Installing Python packages..."
sudo -u "$INSTALL_USER" /home/ari/.local/bin/uv sync
echo -e "${GREEN}Python dependencies installed${NC}"

# Step 3: Download TTS models
if [[ "$AI_MODE" == true ]]; then
    if [[ "$DEV_MODE" == false ]]; then
        echo ""
        echo "Step 3: Downloading TTS models..."
        sudo -u "$INSTALL_USER" bash "$INSTALL_DIR/deploy/download-models.sh" "/home/ari/.local/share/piper"
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
cp "$INSTALL_DIR/deploy/storybot.service" /etc/systemd/system/
cp "$INSTALL_DIR/deploy/storybot-nfc-reset.service" /etc/systemd/system/
cp "$INSTALL_DIR/deploy/storybot-reset-nfc.sh" /usr/local/bin/storybot-reset-nfc.sh
chmod +x /usr/local/bin/storybot-reset-nfc.sh
systemctl daemon-reload
systemctl enable storybot.service
systemctl enable storybot-nfc-reset.service
echo -e "${GREEN}Systemd service installed${NC}"

# Step 6b: Configure passwordless sudo for llama-server control
# The storybot service runs as user `ari` and must stop/start llama-server
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
    cat > /etc/gdm3/custom.conf << 'GDMEOF'
[daemon]
AutomaticLoginEnable=true
AutomaticLogin=ari

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
    sudo -u "$INSTALL_USER" mkdir -p /home/ari/.config/autostart

    cat > /home/ari/.config/autostart/storybot-kiosk.desktop << 'KIOSKEOF'
[Desktop Entry]
Type=Application
Name=StoryBot Kiosk
Comment=Launch Firefox kiosk for StoryBot
Exec=bash -c "unclutter -idle 0.5 & sleep 5 && MOZ_DISABLE_CONTENT_SANDBOX=1 firefox --kiosk --purgecaches --no-remote -P kiosk http://localhost/"
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
KIOSKEOF
    chown "$INSTALL_USER:$INSTALL_USER" /home/ari/.config/autostart/storybot-kiosk.desktop
    echo -e "${GREEN}Kiosk autostart configured${NC}"
else
    echo "Step 9: Skipping Firefox kiosk autostart (stories-only mode)..."
fi

# Step 10: Configure screen-never-blocks (AI/kiosk only)
echo ""
if [[ "$AI_MODE" == true ]]; then
    echo "Step 10: Configuring screen settings..."
    cat > /home/ari/.config/autostart/storybot-screen-setup.desktop << 'SCREENEOF'
[Desktop Entry]
Type=Application
Name=StoryBot Screen Setup
Comment=Disable screen blanking (runs once)
Exec=bash -c "gsettings set org.gnome.desktop.session idle-delay 0 && gsettings set org.gnome.desktop.screensaver lock-enabled false && rm -f ~/.config/autostart/storybot-screen-setup.desktop"
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
SCREENEOF
    chown "$INSTALL_USER:$INSTALL_USER" /home/ari/.config/autostart/storybot-screen-setup.desktop
    echo -e "${GREEN}Screen settings configured${NC}"
else
    echo "Step 10: Skipping screen settings (stories-only mode)..."
fi

# Step 11: Fix file ownership
echo ""
echo "Step 11: Fixing file ownership..."
chown -R "$INSTALL_USER:$INSTALL_USER" "$INSTALL_DIR"
chown -R "$INSTALL_USER:$INSTALL_USER" /home/ari/.config/autostart
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
if [[ "$AI_MODE" == true ]]; then
    echo "  - NVIDIA JetPack (GPU + CUDA)"
    if [[ "$DEV_MODE" == false ]]; then
        echo "  - Piper TTS models at /home/ari/.local/share/piper"
    fi
    echo "  - GDM3 autologin for user ari"
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
