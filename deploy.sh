#!/bin/bash
# KreditKard VPS Deploy Script
# Run this on your VPS after SSH login

set -e

REPO_URL="https://github.com/rShetty/momento.git"
INSTALL_DIR="/opt/kreditkard"
PYTHON_CMD="python3"

echo "========================================"
echo "  KreditKard VPS Deployment"
echo "========================================"
echo

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "⚠️  Warning: Not running as root. Some operations may fail."
    echo "Recommended: sudo bash deploy.sh"
    echo
fi

# Update system
echo "1. Updating system packages..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git curl cron 2>/dev/null || true

# Check Python version
echo
echo "2. Checking Python..."
PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | grep -oP '\d+\.\d+')
REQUIRED_VERSION="3.11"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo "❌ Python $PYTHON_VERSION found. Need 3.11+"
    echo "Installing Python 3.11..."
    apt-get install -y -qq software-properties-common
    add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null || true
    apt-get update -qq
    apt-get install -y -qq python3.11 python3.11-venv python3.11-pip
    PYTHON_CMD="python3.11"
fi

echo "✅ Python ready: $($PYTHON_CMD --version)"

# Clone or update repo
echo
echo "3. Cloning repository..."
if [ -d "$INSTALL_DIR" ]; then
    echo "   Directory exists. Updating..."
    cd "$INSTALL_DIR"
    git pull origin main
else
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

echo "✅ Repository at $INSTALL_DIR"

# Create virtual environment
echo
echo "4. Setting up virtual environment..."
if [ ! -d "$INSTALL_DIR/.venv" ]; then
    $PYTHON_CMD -m venv "$INSTALL_DIR/.venv"
fi
echo "✅ Virtual environment ready"

# Install dependencies
echo
echo "5. Installing Python dependencies..."
"$INSTALL_DIR/.venv/bin/pip" install -q -r requirements.txt
echo "✅ Dependencies installed"

# Check for secrets
echo
echo "6. Checking for required files..."
MISSING_FILES=0

if [ ! -f "$INSTALL_DIR/.env" ]; then
    echo "   ⚠️  .env file NOT FOUND"
    echo "   You need to create it. Template:"
    echo
    echo "   cp .env.example .env"
    echo "   nano .env"
    echo
    echo "   Required values:"
    echo "   TELEGRAM_BOT_TOKEN=your_token"
    echo "   TELEGRAM_CHAT_ID=your_chat_id"
    echo "   TELEGRAM_BOT_USERNAME=@your_bot"
    MISSING_FILES=$((MISSING_FILES + 1))
fi

if [ ! -f "$INSTALL_DIR/token.json" ]; then
    echo "   ⚠️  token.json NOT FOUND"
    echo "   You need to run Gmail authentication:"
    echo
    echo "   cd $INSTALL_DIR"
    echo "   .venv/bin/python auth.py"
    echo
    echo "   This will open a browser for OAuth."
    MISSING_FILES=$((MISSING_FILES + 1))
fi

if [ ! -f "$INSTALL_DIR/client_secret_*.json" ]; then
    echo "   ⚠️  client_secret_*.json NOT FOUND"
    echo "   You need to download this from Google Cloud Console"
    echo "   and place it in $INSTALL_DIR/"
    MISSING_FILES=$((MISSING_FILES + 1))
fi

if [ $MISSING_FILES -gt 0 ]; then
    echo
    echo "❌ MISSING $MISSING_FILES REQUIRED FILE(S)"
    echo
    echo "Please set up the missing files manually, then run this script again."
    echo
    echo "Quick setup guide:"
    echo "1. Transfer files from your local machine:"
    echo "   scp .env token.json client_secret_*.json root@your-vps:$INSTALL_DIR/"
    echo
    echo "2. Then run this script again:"
    echo "   bash deploy.sh"
    echo
    exit 1
fi

echo "✅ All required files present"

# Test pipeline
echo
echo "7. Testing pipeline..."
cd "$INSTALL_DIR"
"$INSTALL_DIR/.venv/bin/python" main.py
echo "✅ Pipeline test complete"

# Set up cron
echo
echo "8. Setting up cron job..."
CRON_CMD="0 8 * * * cd $INSTALL_DIR && $INSTALL_DIR/.venv/bin/python main.py >> $INSTALL_DIR/run.log 2>&1"

# Remove old cron if exists
(crontab -l 2>/dev/null | grep -v "$INSTALL_DIR/main.py" || true) | crontab -

# Add new cron
(crontab -l 2>/dev/null || true; echo "$CRON_CMD") | crontab -

echo "✅ Cron job added: Daily at 8:00 AM"
echo
echo "   View cron: crontab -l"
echo "   Logs: tail -f $INSTALL_DIR/run.log"

# Set up systemd for telegram bot
echo
echo "9. Setting up Telegram bot service..."
cat > /etc/systemd/system/kreditkard-bot.service <<EOF
[Unit]
Description=KreditKard Telegram Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/.venv/bin/python telegram_bot.py
Restart=always
RestartSec=10
User=root

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable kreditkard-bot 2>/dev/null || true

echo "✅ Service configured"
echo
echo "   Start: systemctl start kreditkard-bot"
echo "   Status: systemctl status kreditkard-bot"
echo "   Logs: journalctl -u kreditkard-bot -f"

echo
echo "========================================"
echo "  DEPLOYMENT COMPLETE"
echo "========================================"
echo
echo "Installation directory: $INSTALL_DIR"
echo
echo "Quick commands:"
echo "  cd $INSTALL_DIR"
echo "  .venv/bin/python main.py        # Run pipeline manually"
echo "  .venv/bin/python telegram_bot.py # Start bot (interactive)"
echo "  systemctl start kreditkard-bot   # Start bot (daemon)"
echo "  tail -f run.log                  # View daily run logs"
echo
echo "Telegram commands:"
echo "  /status    - View pending bills"
echo "  /register  - Add a new card"
echo "  /paid <id> - Mark bill as paid"
echo
