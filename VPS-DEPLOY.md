# VPS Deployment Guide

Deploy KreditKard to your VPS in 3 steps.

---

## Prerequisites

- VPS with Ubuntu/Debian
- Root SSH access
- Your local machine has the secrets (`.env`, `token.json`, `client_secret.json`)

---

## Step 1: Transfer Secrets to VPS

**On your local machine**, run:

```bash
# Replace these paths with your actual file locations
LOCAL_DIR="/Users/rshetty/fun/kreditkard"
VPS_IP="187.127.140.12"

# Transfer .env (contains Telegram tokens)
scp "$LOCAL_DIR/.env" root@$VPS_IP:/opt/kreditkard/

# Transfer Gmail OAuth token
scp "$LOCAL_DIR/token.json" root@$VPS_IP:/opt/kreditkard/

# Transfer Google client secret
scp "$LOCAL_DIR"/client_secret_*.json root@$VPS_IP:/opt/kreditkard/
```

**Verify files on VPS:**
```bash
ssh root@187.127.140.12 "ls -la /opt/kreditkard/.env /opt/kreditkard/token.json /opt/kreditkard/client_secret_*.json"
```

---

## Step 2: Run Installer on VPS

**SSH into VPS:**
```bash
ssh root@187.127.140.12
```

**Run the installer:**
```bash
curl -sSL https://raw.githubusercontent.com/rShetty/momento/main/install.sh | bash
```

This will:
1. Install Python 3.11, git, cron
2. Clone repo to `/opt/kreditkard`
3. Create virtual environment
4. Install dependencies
5. Verify secrets exist
6. Test Gmail + Telegram connections
7. Run first pipeline
8. Create systemd service for bot
9. Add daily cron job (8 AM)

---

## Step 3: Verify Installation

**Check services:**
```bash
# Telegram bot status
systemctl status kreditkard-bot

# View bot logs
journalctl -u kreditkard-bot -f

# Check cron job
crontab -l

# View pipeline logs
tail -f /opt/kreditkard/run.log
```

**Test commands:**
```bash
# Manual pipeline run
cd /opt/kreditkard
.venv/bin/python main.py

# Restart bot
systemctl restart kreditkard-bot
```

---

## Troubleshooting

### Missing secrets
If the installer reports missing files, transfer them and re-run:
```bash
# On local machine
scp /path/to/missing_file root@187.127.140.12:/opt/kreditkard/

# On VPS
bash install.sh
```

### Gmail auth expired
```bash
cd /opt/kreditkard
.venv/bin/python auth.py
# Browser will open for re-auth
```

### Bot not responding
```bash
systemctl restart kreditkard-bot
journalctl -u kreditkard-bot -f
```

### Cron not running
```bash
# Check if cron is installed
which cron

# Check cron logs
grep CRON /var/log/syslog

# Manually trigger
cd /opt/kreditkard && .venv/bin/python main.py
```

---

## File Locations

| File | Path |
|------|------|
| Code | `/opt/kreditkard/` |
| Virtual env | `/opt/kreditkard/.venv/` |
| Logs | `/opt/kreditkard/run.log` |
| Database | `/opt/kreditkard/kreditkard.db` |
| PDFs | `/opt/kreditkard/pdfs/` |
| Service config | `/etc/systemd/system/kreditkard-bot.service` |

---

## Updating

```bash
ssh root@187.127.140.12
cd /opt/kreditkard
git pull origin main
.venv/bin/pip install -r requirements.txt
systemctl restart kreditkard-bot
```
