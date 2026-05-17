# KreditKard Setup Guide

## Prerequisites
- Python 3.11+
- A VPS or always-on machine (Ubuntu recommended)
- `cron` for scheduling

---

## 1. Telegram Bot Token & Chat ID

### Create a Bot
1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Follow prompts to name your bot (e.g., `kreditkard_bot`)
4. **BotFather will reply with your token:**
   ```
   123456789:ABCdefGHIjklMNOpqrSTUvwxyz
   ```
   Copy this into `TELEGRAM_BOT_TOKEN=` in your `.env` file.

### Get Your Chat ID
1. Message your new bot `/start`
2. Visit this URL in your browser (replace `<TOKEN>`):
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
3. Look for `"chat":{"id":12345678` — that number is your `TELEGRAM_CHAT_ID`

---

## 2. Gmail OAuth Token

KreditKard uses **read-only** Gmail access. You need an OAuth 2.0 access token.

### Method A: Google Cloud Console (Recommended for long-term use)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (e.g., `kreditkard`)
3. Navigate to **APIs & Services > Library**
4. Search for **Gmail API** and click **Enable**
5. Go to **APIs & Services > OAuth consent screen**
   - Choose **External** (or Internal if GSuite)
   - Fill in app name: `KreditKard`
   - Add scope: `https://www.googleapis.com/auth/gmail.readonly`
   - Add your email as a test user
6. Go to **Credentials > Create Credentials > OAuth client ID**
   - Application type: **Desktop app**
   - Name: `KreditKard Desktop`
7. Download the JSON file (`client_secret_*.json`)
8. Use this Python script to get your token:

```python
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import json

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

flow = InstalledAppFlow.from_client_secrets_file(
    'client_secret_XXXX.json', SCOPES)
creds = flow.run_local_server(port=0)

print('Access token:', creds.token)
print('Refresh token:', creds.refresh_token)
```

9. Copy the **Access token** into `GMAIL_OAUTH_TOKEN=` in your `.env`

### Method B: Google OAuth Playground (Quick & Easy)

1. Visit [Google OAuth 2.0 Playground](https://developers.google.com/oauthplayground/)
2. Click the **gear icon** (⚙️) in top right
   - Check **"Use your own OAuth credentials"**
   - Enter your Client ID and Client Secret from Step 6 above
3. In the left panel, select **Gmail API v1 > https://www.googleapis.com/auth/gmail.readonly**
4. Click **Authorize APIs** → sign in with your Gmail
5. Click **Exchange authorization code for tokens**
6. Copy the **Access token** into your `.env`

> ⚠️ Access tokens expire. For production, store the **Refresh token** and implement auto-refresh (KreditKard currently uses long-lived tokens).

---

## 3. OpenRouter API Key (Optional)

Only needed for LLM fallback on unknown bank statements.

1. Visit [OpenRouter](https://openrouter.ai/)
2. Sign up and get an API key
3. Copy into `OPENROUTER_API_KEY=` in `.env`

Default model: `mistralai/mistral-7b-instruct` (cheap, ~$0.50-1/month for 10 statements)

---

## 4. Configuration

Create `.env` from the example:

```bash
cp .env.example .env
nano .env
```

Fill in:
```env
GMAIL_OAUTH_TOKEN=ya29.a0AR...
OPENROUTER_API_KEY=sk-or-v1-...
TELEGRAM_BOT_TOKEN=123456789:ABCdef...
TELEGRAM_CHAT_ID=12345678
TELEGRAM_BOT_USERNAME=@kreditkard_bot
```

Optional tuning:
```env
CHECK_TIME=08:00
REMINDER_DAYS_BEFORE=7
MAX_REMINDERS_TODAY=1
READ_EMAIL_DAYS_BACK=3
```

---

## 5. Install & Run

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Initialize DB and run once manually
python main.py
```

---

## 6. Schedule with Cron

```bash
crontab -e
```

Add this line (runs daily at 8:00 AM):
```cron
0 8 * * * cd /opt/kreditkard && /opt/kreditkard/.venv/bin/python main.py >> /opt/kreditkard/run.log 2>&1
```

---

## 7. Run Telegram Bot (Optional)

For two-way commands (`/paid`, `/status`, `/teach`):

```bash
# In a separate terminal or screen/tmux session
source .venv/bin/activate
python telegram_bot.py
```

Or run it as a systemd service for production.

---

## Commands

| Command | Action |
|---|---|
| `/start` | Show help |
| `/status` | List all pending dues |
| `/paid hdfc` | Mark latest HDFC bill as paid |
| `/forcecheck` | Run Gmail scan immediately |
| `/teach axis due:25-05-2026 amount:45320 ...` | Teach the bot a new pattern |
| `/confirm axis due:25-05-2026 amount:45320 ...` | Confirm LLM guess and learn |
| `/patterns hdfc` | Show learned patterns for HDFC |
| `/history hdfc` | Show recent HDFC bills |

---

## File Structure

```
kreditkard/
├── main.py                  # Cron entry point
├── telegram_bot.py          # Bot command handlers
├── config.py                # .env loader
├── db.py                    # SQLite layer
├── utils.py                 # Date/amount/text helpers
├── gmail_client.py          # Gmail API wrapper
├── pdf_extractor.py         # PyMuPDF wrapper
├── hdfc_extractor.py        # HDFC-specific parser
├── pattern_matcher.py       # Generic pattern engine
├── pattern_generator.py     # Auto-pattern builder
├── llm_client.py            # OpenRouter fallback
├── payment_detector.py      # Payment email scanner
├── reminder.py              # Telegram reminder sender
├── .env                     # Secrets (gitignored)
├── requirements.txt
├── kreditkard.db            # SQLite DB (gitignored)
└── pdfs/                    # Downloaded PDFs (gitignored)
```

---

## Security Notes

- `.env` and `kreditkard.db` are in `.gitignore` — **never commit them**
- Set strict permissions: `chmod 600 .env`
- Gmail scope is **read-only** — the app cannot send, delete, or mark emails as read
- PDFs are stored locally on your VPS only
- LLM calls send only text snippets, never full binary PDFs
