# Detailed Setup Guide

This guide walks you through every step of setting up KreditKard from scratch.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Telegram Bot Setup](#telegram-bot-setup)
3. [Gmail OAuth Setup](#gmail-oauth-setup)
4. [Environment Configuration](#environment-configuration)
5. [First Run](#first-run)
6. [Cron Setup](#cron-setup)
7. [Troubleshooting](#troubleshooting)

---

## Prerequisites

- Python 3.11 or higher
- A Gmail account
- A Telegram account
- A VPS, Raspberry Pi, or always-on computer (for cron)
- Git

---

## Telegram Bot Setup

### Step 1: Create a Bot with BotFather

1. Open **Telegram** on your phone or desktop
2. Search for: **`@BotFather`**
3. Click **Start** or send `/start`
4. Send `/newbot`
5. BotFather asks for a name:
   - Type: `KreditKard`
6. BotFather asks for a username:
   - Type: `yourname_kard_bot` (must end in `_bot`, must be globally unique)
   - If taken, try `yourname_kreditkard_bot` or similar
7. **BotFather replies with your token:**
   ```
   Done! Congratulations on your new bot.
   You will find it at t.me/yourname_kard_bot
   
   Use this token to access the HTTP API:
   123456789:ABCdefGHIjklMNOpqrSTUvwxyz
   ```

8. **Copy that token immediately** — you'll never see it again in full

### Step 2: Get Your Chat ID

1. Find your bot in Telegram (search `@yourname_kard_bot`)
2. Click **Start** or send any message like `/start` or `hello`
3. The bot needs at least one message to identify your chat

### Step 3: Test the Bot

After setting up `.env` (see below), run:

```bash
python -c "
from telegram import Bot
import asyncio

async def test():
    bot = Bot(token='YOUR_TOKEN_HERE')
    me = await bot.get_me()
    print(f'Bot: @{me.username}')
    
    updates = await bot.get_updates()
    if updates:
        chat_id = updates[-1].message.chat.id
        print(f'Chat ID: {chat_id}')
        
        await bot.send_message(
            chat_id=chat_id,
            text='🤖 KreditKard is online!'
        )
        print('Test message sent!')

asyncio.run(test())
"
```

You should receive a message from your bot.

---

## Gmail OAuth Setup

### Overview

KreditKard uses **OAuth2** (not your Gmail password) to read emails. This is more secure and is the standard way apps access Gmail.

### Step 1: Create a Google Cloud Project

1. Go to: https://console.cloud.google.com/
2. Sign in with the Gmail account you want to monitor
3. Click the project selector (top left)
4. Click **"New Project"**
5. Name it: `KreditKard`
6. Click **Create**

### Step 2: Enable Gmail API

1. In your new project, go to: **APIs & Services → Library**
2. Search for: **"Gmail API"**
3. Click **Gmail API**
4. Click **ENABLE**
5. Wait for it to activate (takes ~1 minute)

### Step 3: Configure OAuth Consent Screen

1. Go to: **APIs & Services → OAuth consent screen**
2. Choose **External** (or Internal if you have Google Workspace)
3. Click **Create**
4. Fill in:
   - **App name**: `KreditKard`
   - **User support email**: Your email
   - **Developer contact email**: Your email
5. Click **Save and Continue**
6. On **Scopes** page:
   - Click **Add or Remove Scopes**
   - Search for: `https://www.googleapis.com/auth/gmail.readonly`
   - Check the box
   - Click **Update**
   - Click **Save and Continue**
7. On **Test users** page:
   - Click **+ ADD USERS**
   - Enter your Gmail address
   - Click **Add**
   - Click **Save and Continue**
8. Review and click **Back to Dashboard**

### Step 4: Create OAuth Credentials

1. Go to: **APIs & Services → Credentials**
2. Click **+ CREATE CREDENTIALS → OAuth client ID**
3. Application type: **Web application**
4. Name: `KreditKard Desktop`
5. Under **Authorized redirect URIs**:
   - Click **+ ADD URI**
   - Enter: `http://localhost:8080`
   - (This is where our local auth server listens)
6. Click **CREATE**
7. A popup appears with your **Client ID** and **Client Secret**
8. Click **DOWNLOAD JSON**
9. Save the file to your project directory
   - Filename will be like: `client_secret_123456789-xxx.apps.googleusercontent.com.json`

### Step 5: Run Authentication

```bash
python auth.py
```

This will:
1. Start a local server on `http://localhost:8080`
2. Open your browser to Google's OAuth page
3. Ask you to select your Gmail account and approve
4. Redirect back to localhost with an auth code
5. Exchange the code for access + refresh tokens
6. Save `token.json` (this is your permanent key — keep it safe)

**Note:** `token.json` contains your refresh token. Do not share or commit it.

---

## Environment Configuration

Create `.env` in the project root:

```bash
cp .env.example .env
```

Edit `.env` with your actual values:

```env
# Gmail (OAuth - you don't need to fill these manually, auth.py handles it)
# Just keep empty — auth.py creates token.json
GMAIL_OAUTH_TOKEN=

# Telegram (required)
TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID=YOUR_CHAT_ID_HERE
TELEGRAM_BOT_USERNAME=@kredit_kard_bot

# LLM (optional — leave blank to skip LLM features)
OPENROUTER_API_KEY=
OPENROUTER_MODEL=mistralai/mistral-7b-instruct

# Behaviour
CHECK_TIME=08:00
REMINDER_DAYS_BEFORE=7
MAX_REMINDERS_TODAY=1
READ_EMAIL_DAYS_BACK=30
```

### Getting Your Chat ID Programmatically

After messaging your bot `/start`, run:

```python
from telegram import Bot
import asyncio

async def main():
    bot = Bot(token='YOUR_BOT_TOKEN')
    updates = await bot.get_updates()
    for u in updates:
        print(f"Chat ID: {u.message.chat.id}")
        print(f"User: {u.message.from_user.first_name}")

asyncio.run(main())
```

---

## First Run

### Test Gmail Connection

```bash
python -c "
from gmail_client import test_connection
result = test_connection()
print(f'Email: {result[\"email\"]}')
print(f'Messages: {result[\"messages_total\"]}')
"
```

### Run Full Pipeline

```bash
python main.py
```

You should see output like:
```
[main] Found 7 statement emails.
[main] Matched to registered card: Swiggy Card
[main] Saved bill via pattern: ...
```

### Start Telegram Bot (for commands)

In a separate terminal:

```bash
python telegram_bot.py
```

The bot will start polling for commands like `/status`, `/paid`, `/register`.

---

## Cron Setup

Edit your crontab:

```bash
crontab -e
```

Add this line to run every morning at 8 AM:

```cron
0 8 * * * cd /path/to/momento && /path/to/momento/.venv/bin/python main.py >> /path/to/momento/run.log 2>&1
```

For testing, run every 5 minutes:

```cron
*/5 * * * * cd /path/to/momento && /path/to/momento/.venv/bin/python main.py >> /path/to/momento/run.log 2>&1
```

**Note:** The `telegram_bot.py` should run as a systemd service or in a `screen`/`tmux` session since it needs to stay alive to accept commands.

### Systemd Service (for VPS)

Create `/etc/systemd/system/kreditkard-bot.service`:

```ini
[Unit]
Description=KreditKard Telegram Bot
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/momento
ExecStart=/path/to/momento/.venv/bin/python telegram_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl enable kreditkard-bot
sudo systemctl start kreditkard-bot
sudo systemctl status kreditkard-bot
```

---

## Troubleshooting

### Gmail OAuth Issues

**"Access blocked: This app’s request is invalid"**
- You didn't add your email as a test user in OAuth consent screen
- Go to APIs & Services → OAuth consent screen → Test users → Add your email

**"Gmail API has not been used in project before or it is disabled"**
- Gmail API isn't enabled yet. Go to Library → Gmail API → Enable
- Wait 2-3 minutes after enabling

**"redirect_uri_mismatch"**
- The redirect URI in your request doesn't match what's in Google Cloud Console
- Go to Credentials → Your client ID → Add `http://localhost:8080` to Authorized redirect URIs

**Token expired**
- The `token.json` handles refresh automatically
- If it fails, delete `token.json` and re-run `python auth.py`

### Telegram Issues

**"Chat not found"**
- You haven't messaged the bot yet
- Message `@yourbot /start` first

**"Bot blocked by user"**
- You blocked the bot. Unblock it in Telegram settings

### Missing Statements

**No emails found**
- Check if sender address is in `config.py` `BANK_SENDERS`
- Increase `READ_EMAIL_DAYS_BACK` in `.env`
- Check Gmail search: `from:hdfcbank.net has:attachment filename:pdf`

**PDF won't open**
- Check if card is registered with correct last-4 digits
- Verify cardholder name matches exactly as on card
- Try the password manually: first 4 letters of name + last 4 digits of card

---

## Updating

```bash
git pull origin main
.venv/bin/pip install -r requirements.txt
```

If database schema changed, you may need to delete `kreditkard.db` and re-register cards (data loss: only registered cards, not parsed bills).
