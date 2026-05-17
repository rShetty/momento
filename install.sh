#!/bin/bash
# KreditKard VPS Installation Script
# Usage: curl -sSL https://raw.githubusercontent.com/rShetty/momento/main/install.sh | bash

set -e

INSTALL_DIR="/opt/kreditkard"
LOG_FILE="/var/log/kreditkard.log"
PYTHON_CMD=""

echo "=========================================="
echo "  KreditKard VPS Installer"
echo "=========================================="
echo ""

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$NAME
    VER=$VERSION_ID
else
    echo "Cannot detect OS. This script supports Ubuntu/Debian."
    exit 1
fi

echo "Detected: $OS $VER"
echo ""

# Update system
echo "Step 1/10: Updating system packages..."
apt-get update -qq > /dev/null 2>&1
apt-get install -y -qq curl wget git cron 2>/dev/null || true
echo "✓ System updated"
echo ""

# Find or install Python 3.11+
echo "Step 2/10: Checking Python..."
PYTHON_VERSION=""

# Check existing Python installations
for py in python3.11 python3.12 python3.13 python3.14; do
    if command -v $py &> /dev/null; then
        PYTHON_CMD=$py
        PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | grep -oP '\d+\.\d+')
        break
    fi
done

# Install Python 3.11 if not found
if [ -z "$PYTHON_CMD" ]; then
    echo "  → Python 3.11+ not found. Installing..."
    apt-get install -y -qq software-properties-common 2>/dev/null || true
    
    # Try deadsnakes PPA for Ubuntu
    if echo "$OS" | grep -qi "ubuntu"; then
        add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null || true
        apt-get update -qq > /dev/null 2>&1
    fi
    
    # Install python3.11 and required packages
    apt-get install -y -qq python3.11 python3.11-venv python3.11-pip python3.11-dev 2>/dev/null || {
        echo "✗ Failed to install Python 3.11. Trying Python 3.10..."
        apt-get install -y -qq python3 python3-venv python3-pip python3-dev 2>/dev/null || {
            echo "✗ Cannot install Python. Please install Python 3.11+ manually."
            exit 1
        }
        PYTHON_CMD="python3"
        PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | grep -oP '\d+\.\d+')
    }
    
    if [ -z "$PYTHON_VERSION" ]; then
        PYTHON_CMD="python3.11"
        PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | grep -oP '\d+\.\d+') || {
            echo "✗ Python installation failed"
            exit 1
        }
    fi
fi

echo "✓ Python $PYTHON_VERSION found ($PYTHON_CMD)"
echo ""

# Clone repository
echo "Step 3/10: Cloning repository..."
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "  → Repository exists, updating..."
    cd "$INSTALL_DIR"
    git pull origin main 2>&1 | tail -5
else
    echo "  → Cloning from GitHub..."
    git clone https://github.com/rShetty/momento.git "$INSTALL_DIR" 2>&1 | tail -5
fi
echo "✓ Repository at $INSTALL_DIR"
echo ""

# Create virtual environment
echo "Step 4/10: Creating virtual environment..."
cd "$INSTALL_DIR"

if [ ! -d "$INSTALL_DIR/.venv" ]; then
    $PYTHON_CMD -m venv "$INSTALL_DIR/.venv"
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment already exists"
fi
echo ""

# Install dependencies
echo "Step 5/10: Installing dependencies..."
"$INSTALL_DIR/.venv/bin/pip" install --no-cache-dir -q -r "$INSTALL_DIR/requirements.txt"
echo "✓ Dependencies installed"
echo ""

# Check for required secret files
echo "Step 6/10: Checking required files..."
echo ""

MISSING=0

if [ ! -f "$INSTALL_DIR/.env" ]; then
    echo "  ⚠️  .env NOT FOUND"
    echo "     You need to create $INSTALL_DIR/.env"
    echo "     Copy from .env.example and fill in your tokens:"
    echo "       TELEGRAM_BOT_TOKEN=your_token"
    echo "       TELEGRAM_CHAT_ID=your_chat_id"
    echo ""
    MISSING=$((MISSING + 1))
else
    echo "  ✓ .env found"
fi

if [ ! -f "$INSTALL_DIR/token.json" ]; then
    echo "  ⚠️  token.json NOT FOUND"
    echo "     You need to authenticate with Gmail:"
    echo "       cd $INSTALL_DIR && .venv/bin/python auth.py"
    echo "     This will open a browser for OAuth."
    echo ""
    MISSING=$((MISSING + 1))
else
    echo "  ✓ token.json found"
fi

if ! ls "$INSTALL_DIR"/client_secret_*.json >/dev/null 2>&1; then
    echo "  ⚠️  client_secret_*.json NOT FOUND"
    echo "     Download from Google Cloud Console and place in $INSTALL_DIR/"
    echo ""
    MISSING=$((MISSING + 1))
else
    echo "  ✓ client_secret found"
fi

if [ $MISSING -gt 0 ]; then
    echo "========================================"
    echo "  ⚠️  MISSING $MISSING REQUIRED FILE(S)"
    echo "========================================"
    echo ""
    echo "Please provide the missing files, then re-run this script."
    echo ""
    echo "To transfer files from your local machine:"
    echo ""
    echo "  scp /path/to/.env root@YOUR_VPS_IP:$INSTALL_DIR/"
    echo "  scp /path/to/token.json root@YOUR_VPS_IP:$INSTALL_DIR/"
    echo "  scp /path/to/client_secret_*.json root@YOUR_VPS_IP:$INSTALL_DIR/"
    echo ""
    echo "After transferring, run: bash install.sh"
    echo ""
    exit 1
fi

echo ""
echo "✓ All required files present"
echo ""

# Test Gmail connection
echo "Step 7/10: Testing Gmail connection..."
cd "$INSTALL_DIR"
if ! "$INSTALL_DIR/.venv/bin/python" -c "from gmail_client import test_connection; result = test_connection(); print(f'Gmail: {result[\"email\"]}')" 2>&1; then
    echo "  ⚠️  Gmail test failed. Run auth.py:"
    echo "     cd $INSTALL_DIR && .venv/bin/python auth.py"
    echo ""
    MISSING=$((MISSING + 1))
else
    echo "✓ Gmail connected"
fi
echo ""

# Test Telegram
echo "Step 8/10: Testing Telegram connection..."
if "$INSTALL_DIR/.venv/bin/python" -c "
from reminder import send_message
import os
os.chdir('$INSTALL_DIR')
result = send_message('🤖 KreditKard deployed to VPS successfully!')
print(f'Telegram: {result}')
" 2>&1; then
    echo "✓ Telegram connected"
else
    echo "  ⚠️  Telegram test failed. Check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env"
fi
echo ""

# Run first pipeline test
echo "Step 9/10: Running test pipeline..."
if "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/main.py" 2>&1 | head -20; then
    echo "✓ Pipeline test complete"
else
    echo "  ⚠️  Pipeline test had issues (check logs above)"
fi
echo ""

# Setup systemd service for Telegram bot
echo "Step 10/10: Setting up services..."
echo ""

# Create systemd service
cat > /etc/systemd/system/kreditkard-bot.service <<'EOF'
[Unit]
Description=KreditKard Telegram Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/kreditkard
ExecStart=/opt/kreditkard/.venv/bin/python telegram_bot.py
Restart=always
RestartSec=10
User=root
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Create cron job for daily run
CRON_LINE="0 8 * * * cd /opt/kreditkard && /opt/kreditkard/.venv/bin/python main.py >> /opt/kreditkard/run.log 2>&1"

# Remove old cron job if exists
(crontab -l 2>/dev/null | grep -v "kreditkard/main.py" || true) | crontab -

# Add new cron job
(crontab -l 2>/dev/null || true; echo "$CRON_LINE") | crontab -

# Reload systemd and enable service
systemctl daemon-reload > /dev/null 2>&1
systemctl enable kreditkard-bot > /dev/null 2>&1
systemctl start kreditkard-bot > /dev/null 2>&1

echo "✓ Telegram bot service created and started"
echo "✓ Daily cron job added (8:00 AM)"
echo ""

# Final summary
echo "=========================================="
echo "  INSTALLATION COMPLETE!"
echo "=========================================="
echo ""
echo "Installation directory: $INSTALL_DIR"
echo ""
echo "Services:"
echo "  Bot:     systemctl status kreditkard-bot"
echo "  Logs:    journalctl -u kreditkard-bot -f"
echo "  Cron:    crontab -l"
echo "  Run log: tail -f /opt/kreditkard/run.log"
echo ""
echo "Management commands:"
echo "  cd $INSTALL_DIR"
echo "  .venv/bin/python main.py        # Run pipeline manually"
echo "  .venv/bin/python telegram_bot.py # Start bot manually"
echo "  systemctl start kreditkard-bot   # Start bot daemon"
echo "  systemctl stop kreditkard-bot    # Stop bot daemon"
echo "  systemctl restart kreditkard-bot # Restart bot"
echo ""
echo "Telegram commands:"
echo "  /status    - View pending bills"
echo "  /register  - Add a new card"
echo "  /paid <id> - Mark bill as paid"
echo "  /forcecheck - Run Gmail scan now"
echo ""

# Verify bot is running
if systemctl is-active kreditkard-bot >/dev/null 2>&1; then
    echo "✅ Telegram bot is RUNNING"
else
    echo "⚠️  Telegram bot is NOT running. Check: systemctl status kreditkard-bot"
fi

echo ""
echo "Done!"
