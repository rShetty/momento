"""Central configuration for KreditKard."""

import os
import pathlib

from dotenv import load_dotenv

# Load .env from project root
load_dotenv()

# ── Paths ───────────────────────────────────────
ROOT = pathlib.Path(__file__).parent.resolve()
PDF_DIR = ROOT / "pdfs"
PDF_DIR.mkdir(exist_ok=True)
DB_PATH = ROOT / os.getenv("DB_PATH", "kreditkard.db")

# ── Secrets ─────────────────────────────────────
GMAIL_OAUTH_TOKEN = os.getenv("GMAIL_OAUTH_TOKEN", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "mistralai/mistral-7b-instruct")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "@kreditkard_bot")

# ── Behaviour ───────────────────────────────────
CHECK_TIME = os.getenv("CHECK_TIME", "08:00")
REMINDER_DAYS_BEFORE = int(os.getenv("REMINDER_DAYS_BEFORE", "7"))
MAX_REMINDERS_TODAY = int(os.getenv("MAX_REMINDERS_TODAY", "1"))
READ_EMAIL_DAYS_BACK = int(os.getenv("READ_EMAIL_DAYS_BACK", "30"))

# ── Bank senders (key -> email domain / exact address) ───
# NOTE: These should match the actual "From" addresses seen in Gmail
BANK_SENDERS = {
    "hdfc": [
        "alerts@hdfcbank.net",
        "Emailstatements.cards@hdfcbank.net",
        "information@mailers.hdfcbank.net",
    ],
    "axis": ["statements@axisbank.com", "alerts@axisbank.com"],
    "icici": ["alerts@icicibank.com", "credit.cards@icicibank.com"],
    "sbi": ["alerts@sbi.co.in", "onlinesbi@sbi.co.in"],
    "amex": ["statements@welcome.aexp.com", "online.statements@aexp.com"],
    "citi": ["alerts@citi.com", "statements@citibank.com"],
    "kotak": ["alerts@kotak.com", "statements@kotak.com"],
    "indusind": ["statements@indusind.com", "alerts@indusind.com"],
    "rbl": ["statements@rblbank.com"],
}

# ── Payment detection keywords ──────────────────
PAYMENT_KEYWORDS = [
    "payment received",
    "credit card payment",
    "card payment",
    "upi",
    "neft",
    "imps",
    "rtgs",
    "autopay",
    "auto debit",
    "payment success",
    "bill payment",
    "credit card bill",
    "credited to your card",
]


# ── Payment detection keywords ──────────────────
PAYMENT_KEYWORDS = [
    "payment received",
    "credit card payment",
    "card payment",
    "upi",
    "neft",
    "imps",
    "rtgs",
    "autopay",
    "auto debit",
    "payment success",
    "bill payment",
    "credit card bill",
    "credited to your card",
]

# ── Bank password patterns ──────────────────────
# Common patterns for statement PDF passwords:
#   {first4}   = first 4 chars of cardholder name (uppercase)
#   {last4}    = last 4 digits of card number
#   {ddmm}     = DDMM of DOB (not implemented, user provides hint)
BANK_PASSWORD_PATTERNS = {
    "hdfc": [
        "{first4}{last4}",      # e.g. RAJE3464
        "{last4}",                # fallback: just last 4
    ],
    "axis": [
        "{first4}{last4}",
    ],
    "icici": [
        "{first4}{last4}",
    ],
    "sbi": [
        "{last4}",
    ],
    "amex": [
        "{first4}{last4}",
    ],
    "citi": [
        "{last4}",
    ],
    "kotak": [
        "{last4}",
    ],
    "indusind": [
        "{last4}",
    ],
    "rbl": [
        "{last4}",
    ],
}


def all_senders() -> list[str]:
    """Flatten all configured bank sender addresses."""
    return [email for addrs in BANK_SENDERS.values() for email in addrs]


def bank_for_sender(sender_email: str) -> str | None:
    """Return the bank key (e.g. 'hdfc') for a given sender e-mail."""
    cleaned = sender_email.strip().lower()
    for key, addrs in BANK_SENDERS.items():
        if any(addr.lower() in cleaned for addr in addrs):
            return key
    return None


def generate_pdf_password(bank_key: str, cardholder_name: str, last_4_digits: str, password_hint: str | None = None) -> str:
    """Generate the most likely PDF password for a bank statement."""
    if password_hint and "{first4}" in password_hint:
        first4 = cardholder_name.replace(" ", "").upper()[:4]
        return password_hint.replace("{first4}", first4).replace("{last4}", last_4_digits)
    if password_hint and "{last4}" in password_hint:
        return password_hint.replace("{last4}", last_4_digits)

    # Default bank patterns
    patterns = BANK_PASSWORD_PATTERNS.get(bank_key, ["{last4}"])
    first4 = cardholder_name.replace(" ", "").upper()[:4]
    pw = patterns[0].replace("{first4}", first4).replace("{last4}", last_4_digits)
    return pw
