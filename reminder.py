"""Reminder sender (calls Telegram) with beautiful card formatting."""

from datetime import datetime, timedelta

import requests

from config import MAX_REMINDERS_TODAY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
import db


TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def send_message(text: str, parse_mode: str = "Markdown") -> bool:
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
                "parse_mode": parse_mode,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        print(f"Telegram send failed: {exc}")
        return False


def _urgency_emoji(days_left: int) -> str:
    """Return urgency indicator based on days left."""
    if days_left < 0:
        return "🔴 OVERDUE"
    elif days_left <= 2:
        return "🔴 URGENT"
    elif days_left <= 5:
        return "🟠 SOON"
    elif days_left <= 10:
        return "🟡 UPCOMING"
    else:
        return "🟢 SAFE"


def _format_card_border(content_lines: list[str], width: int = 36) -> str:
    """Wrap content in a beautiful box-drawing border."""
    top = "┌" + "─" * width + "┐"
    bottom = "└" + "─" * width + "┘"
    
    formatted = [top]
    for line in content_lines:
        # Pad or truncate to fit width
        visible_len = len(line.replace("*", "").replace("_", "").replace("`", "").replace("₹", "R"))
        padding = max(0, width - visible_len)
        formatted.append("│ " + line + " " * padding + " │")
    formatted.append(bottom)
    
    return "\n".join(formatted)


def _format_reminder(bill: dict, days_left: int) -> str:
    """Format a beautiful card-style reminder for a pending bill."""
    card = bill.get("card_name") or bill["bank_key"].upper()
    mask = bill.get("card_mask") or ""
    
    # Format due date nicely
    due_raw = bill.get("due_date", "")
    try:
        due_dt = datetime.strptime(due_raw, "%Y-%m-%d %H:%M:%S")
        due_str = due_dt.strftime("%d %b %Y")
        due_weekday = due_dt.strftime("%A")
    except (ValueError, TypeError):
        due_str = due_raw[:10]
        due_weekday = ""
    
    # Format statement date
    stmt_raw = bill.get("statement_date", "")
    try:
        stmt_dt = datetime.strptime(stmt_raw, "%Y-%m-%d %H:%M:%S")
        stmt_str = stmt_dt.strftime("%d %b %Y")
    except (ValueError, TypeError):
        stmt_str = stmt_raw[:10]
    
    amt = bill.get("amount")
    cycle = bill.get("bill_cycle") or ""
    bid = bill.get("id", "?")
    
    urgency = _urgency_emoji(days_left)
    
    # Build card content lines
    lines = []
    
    # Header
    lines.append(f"💳 *{card}*")
    if mask:
        lines.append(f"🔒 `{mask}`")
    lines.append("")  # spacer
    
    # Urgency banner
    if days_left < 0:
        lines.append(f"{urgency} — *{abs(days_left)} days past due!*")
    else:
        lines.append(f"{urgency} — *{days_left} days left*")
    lines.append("")
    
    # Details
    lines.append(f"📅 *Due Date:* `{due_str}`")
    if due_weekday:
        lines.append(f"📆 *Day:* {due_weekday}")
    lines.append(f"📄 *Statement:* `{stmt_str}`")
    if cycle:
        lines.append(f"🔄 *Cycle:* `{cycle}`")
    lines.append("")
    
    # Amount - make it big and bold
    if amt is not None:
        lines.append(f"💰 *Amount Due:* `₹{amt:,.2f}`")
    else:
        lines.append("💰 *Amount Due:* Unknown")
    lines.append("")
    
    # Action
    lines.append(f"✅ Reply `/paid {bid}` when done")
    
    return _format_card_border(lines)


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


def notify_failure(bank_key: str, pdf_path: str, raw_snippet: str, llm_guess: dict | None) -> bool:
    """Let user know we couldn't parse a statement — formatted nicely."""
    lines = [
        f"⚠️ *Parse Failed: {bank_key.upper()}*",
        "",
        f"📄 PDF: `{pdf_path}`",
        "",
        "*Raw snippet:*",
        f"```\n{raw_snippet[:500]}\n```",
    ]
    if llm_guess:
        lines.append(f"🤖 *LLM guess:* `{llm_guess}`")
    lines.append("")
    lines.append("*Teach me:*")
    lines.append(f"`/teach {bank_key} due:DD-MM-YYYY amount:XXXXX stmt:DD-MM-YYYY`")
    
    text = _format_card_border(lines, width=40)
    return send_message(text)


def notify_daily_summary(processed: int, reminded: int, paid_detected: int, failures: int) -> bool:
    """End-of-run summary to Telegram — dashboard style."""
    lines = [
        "📊 *KreditKard Daily Summary*",
        "",
        f"📧 Emails processed: `{processed}`",
        f"🔔 Reminders sent: `{reminded}`",
        f"💳 Auto-paid detected: `{paid_detected}`",
        f"❌ Parse failures: `{failures}`",
    ]
    
    # Add status indicator
    if failures > 0:
        lines.append("")
        lines.append("⚠️ Some statements failed to parse. Check `/status`.")
    
    text = _format_card_border(lines, width=38)
    return send_message(text)


def notify_upload_needed(bank_key: str, email: dict) -> bool:
    """Send Telegram asking user to upload the PDF manually — card style."""
    lines = [
        f"📎 *{bank_key.upper()} Statement Notification*",
        "",
        "I found an email but couldn't extract the details.",
        "",
        f"📧 Subject: `{email.get('subject', 'N/A')}`",
        "",
        "*Please download the PDF and upload it here,*",
        "*or forward it to me.*",
    ]
    
    text = _format_card_border(lines, width=40)
    return send_message(text)
