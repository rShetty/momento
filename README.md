# KreditKard

A stupid-simple, open-source CRED alternative for India. Reads your Gmail for credit card statements, parses PDFs, extracts due dates and amounts, and sends you daily reminders on Telegram.

No app. No bloat. Just Python, SQLite, and cron.

---

## Features

- **Gmail Scanning** — Automatically finds statement emails from HDFC, Axis, ICICI, SBI, and more
- **PDF Parsing** — Bank-specific extractors + learning engine for unknown statements
- **Auto-Password Unlock** — Uses your registered card details to guess PDF passwords
- **Payment Detection** — Auto-marks bills as paid via CRED confirmations and bank debit alerts
- **Telegram Reminders** — Daily morning reminders with exact due date and amount
- **Self-Learning** — When a new bank format appears, the bot asks you to `/teach` it
- **Multi-Card Support** — Register multiple cards per bank, all tracked independently

---

## Architecture

```
Daily Cron (8 AM)
    │
    ▼
[Gmail API] → Fetch statement emails with PDFs
    │
    ▼
[PDF Extractor] → Try passwords from registered cards
    │
    ▼
[Bank Extractors] → Try HDFC, Axis, ICICI parsers
    │
    ▼
[Pattern Matcher] → Try learned regex patterns
    │
    ▼
[LLM Fallback] → Ask OpenRouter to parse unknown text
    │
    ▼
[Payment Detector] → Scan for CRED / bank debit alerts
    │
    ▼
[Telegram] → Send reminder for pending dues
```

---

## Quick Start

### 1. Clone and Setup

```bash
git clone https://github.com/rShetty/momento.git
cd momento
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Create Telegram Bot

Message **@BotFather** on Telegram:

1. Send `/newbot`
2. Name it: `KreditKard`
3. Username it: `yourname_kard_bot` (must end in `_bot`)
4. **Copy the token** BotFather gives you

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env`:
```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
# (we'll get Chat ID in step 5)
```

### 4. Setup Gmail OAuth

**You need:** Google Cloud project with Gmail API enabled

**Run the auth helper:**
```bash
python auth.py
```

This will:
1. Print a Google OAuth URL
2. Open your browser
3. Ask you to login and approve
4. Save `token.json` locally (never commit this)

**Prerequisites for auth.py:**
- Download your `client_secret_XXX.json` from Google Cloud Console
- Place it in the project root
- Add `http://localhost:8080` as an authorized redirect URI

See [SETUP.md](SETUP.md) for detailed Google Cloud Console steps.

### 5. Get Your Telegram Chat ID

1. Message your bot `/start`
2. Run this quick script:
```bash
python -c "
from telegram import Bot
import asyncio

async def main():
    bot = Bot(token='YOUR_BOT_TOKEN')
    updates = await bot.get_updates()
    if updates:
        print(f'Chat ID: {updates[-1].message.chat.id}')

asyncio.run(main())
"
```

3. Put that Chat ID in your `.env`

### 6. Register Your Cards

Message your bot:
```
/register
```

Follow the wizard:
1. Select bank (HDFC, Axis, etc.)
2. Enter cardholder name (as on card)
3. Enter last 4 digits
4. Give it a nickname (e.g., "My Swiggy Card")
5. Confirm or customize the PDF password pattern

### 7. Test Run

```bash
python main.py
```

You should see:
- Gmail emails found
- PDFs downloaded
- Bills parsed and saved
- Reminders sent to Telegram

### 8. Set Up Cron

```bash
crontab -e
```

Add:
```cron
0 8 * * * cd /path/to/momento && /path/to/momento/.venv/bin/python main.py >> /path/to/momento/run.log 2>&1
```

---

## Commands

| Command | Action |
|---------|--------|
| `/start` | Show all commands |
| `/register` | Add a new credit card (wizard) |
| `/my_cards` | List registered cards |
| `/delete_card <id>` | Remove a registered card |
| `/status` | Show pending dues |
| `/paid <bill_id>` | Mark a specific bill as paid |
| `/paid <bank> <MM>` | Mark bank's bill for month as paid |
| `/forcecheck` | Run Gmail scan immediately |
| `/teach <bank> due:XX amount:XX ...` | Teach the bot a new format |
| `/confirm <bank> due:XX amount:XX ...` | Confirm LLM guess and learn |
| `/patterns <bank>` | Show learned patterns |
| `/history <bank>` | Show recent bills |

---

## File Structure

```
momento/
├── main.py                  # Cron entry point
├── telegram_bot.py          # Bot command handlers
├── config.py                # Settings & bank mappings
├── db.py                    # SQLite persistence
├── utils.py                 # Date/amount/text helpers
├── gmail_client.py          # Gmail API wrapper
├── pdf_extractor.py         # PyMuPDF wrapper
├── hdfc_extractor.py        # Bank-specific parsers
├── pattern_matcher.py       # Generic pattern engine
├── pattern_generator.py     # Auto-pattern builder
├── llm_client.py            # OpenRouter fallback
├── payment_detector.py      # CRED / bank payment scanner
├── reminder.py              # Telegram sender
├── auth.py                  # Gmail OAuth helper
├── .env                     # Your secrets (gitignored)
├── .env.example             # Template
├── requirements.txt
├── SETUP.md                 # Detailed setup guide
└── README.md                # This file
```

---

## Security

- `.env` and `token.json` are in `.gitignore` — **never commit them**
- Gmail scope is **read-only** — cannot send, delete, or mark emails as read
- PDFs are stored locally, never uploaded
- LLM calls send only text snippets, never full binary PDFs

---

## Contributing

This is a personal project but PRs welcome:
- Add extractors for more Indian banks
- Improve PDF password pattern detection
- Better payment confirmation matching

---

## License

MIT. Do whatever you want. Not responsible if you miss a payment.
