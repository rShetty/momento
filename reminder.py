"""Reminder sender (calls Telegram)."""

from datetime import datetime, timedelta

import requests

from config import MAX_REMINDERS_TODAY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
import db


TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def send_message(text: str) -> bool:
    """Fire-and-forget Telegram message."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured; would have sent:")
        print(text)
        return False

    try:
        resp = requests.post(
            f"{TELEGRAM_URL}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "Markdown",
            },
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        print(f"Telegram send failed: {exc}")
        return False


def remind_pending() -> list[dict]:
    """Send daily reminders for pending bills. Returns list of sent reminders."""
    now = datetime.utcnow()
    upcoming = []
    for bill in db.get_pending_bills():
        due_raw = bill.get("due_date")
        if not due_raw:
            continue
        try:
            due = datetime.strptime(due_raw, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            continue
        days_left = (due - now).days
        if days_left <= MAX_REMINDERS_TODAY:
            upcoming.append((bill, days_left))

    sent: list[dict] = []
    for bill, days_left in upcoming:
        if db.was_reminded_today(bill["id"]):
            continue
        text = _format_reminder(bill, days_left)
        ok = send_message(text)
        if ok:
            db.log_reminder(bill["id"], text)
            sent.append({"bill_id": bill["id"], "days_left": days_left})
    return sent


def _format_reminder(bill: dict, days_left: int) -> str:
    card = bill.get("card_name") or bill["bank_key"].upper()
    mask = bill.get("card_mask") or ""
    due = (bill.get("due_date") or "")[:10]
    stmt = (bill.get("statement_date") or "")[:10]
    amt = bill.get("amount")
    cycle = bill.get("bill_cycle") or ""
    bid = bill.get("id", "?")

    lines = [
        f"💳 *{card}* {mask}",
        f"Bill #{bid}",
        f"Statement: {stmt}",
        f"Due: *{due}* ({days_left} days left)",
        f"Amount: *₹{amt:,.2f}*" if amt else "Amount: unknown",
    ]
    if cycle:
        lines.append(f"Cycle: {cycle}")
    lines.append(f"Reply `/paid {bid}` when done.")
    return "\n".join(lines)


def notify_failure(bank_key: str, pdf_path: str, raw_snippet: str, llm_guess: dict | None) -> bool:
    """Let user know we couldn't parse a statement."""
    text = (
        f"⚠️ Could not parse *{bank_key.upper()}* statement.\n"
        f"PDF: `{pdf_path}`\n\n"
        f"Here is a snippet:\n```\n{raw_snippet[:600]}\n```\n"
    )
    if llm_guess:
        text += f"\nLLM best guess: `{llm_guess}`\n"
    text += (
        f"\nPlease teach me:\n"
        f"`/teach {bank_key} due:DD-MM-YYYY amount:XXXXX stmt:DD-MM-YYYY cycle:XX card:\"Name\" mask:XXXX-1234`"
    )
    return send_message(text)


def notify_daily_summary(processed: int, reminded: int, paid_detected: int, failures: int) -> bool:
    """End-of-run summary to Telegram."""
    text = (
        f"📊 *KreditKard Daily Summary*\n"
        f"Emails processed: {processed}\n"
        f"Reminders sent: {reminded}\n"
        f"Auto-paid detected: {paid_detected}\n"
        f"Parse failures: {failures}\n"
    )
    return send_message(text)
