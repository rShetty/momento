"""Telegram bot: command handlers and long-polling runner."""

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import TELEGRAM_BOT_TOKEN, BANK_SENDERS, generate_pdf_password
import db
from pattern_generator import generate_patterns_from_teach
from main import daily_run
from reminder import send_message
from pdf_extractor import extract_text
from pattern_matcher import parse_statement, llm_fallback, heuristic_fallback
from pattern_generator import auto_save_patterns_from_llm


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 *KreditKard Bot*\n"
        "Commands:\n"
        "`/register` – add a new credit card\n"
        "`/my_cards` – list your registered cards\n"
        "`/delete_card <id>` – remove a registered card\n"
        "`/status` – pending dues\n"
        "`/paid <bank>` – mark latest bill paid\n"
        "`/forcecheck` – run scan now\n"
        "`/teach <bank> due:DD-MM-YYYY amount:XXXX ...`\n"
        "`/confirm <bank> due:XX amount:XX ...`\n"
        "`/patterns <bank>` – show learned patterns\n"
        "`/history <bank>` – recent bills\n\n"
        "📎 You can also *send me a PDF* directly to parse a statement!",
        parse_mode="Markdown",
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    pending = db.get_pending_bills()
    if not pending:
        await update.message.reply_text("✅ No pending dues!")
        return

    lines = ["📋 *Pending Dues*"]
    for bill in pending:
        card = bill.get("card_name") or bill["bank_key"].upper()
        mask = bill.get("card_mask") or ""
        due = (bill.get("due_date") or "")[:10]
        amt = bill.get("amount")
        days = _days_left(bill.get("due_date"))
        bid = bill.get("id", "?")
        lines.append(f"`#{bid}` {card} {mask} — ₹{amt:,.2f} due {due} ({days}d)")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def paid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Mark a bill as paid. Usage:
      /paid <bill_id>           e.g. /paid 3
      /paid <bank> <MM>         e.g. /paid hdfc 05
    """
    if not context.args:
        await update.message.reply_text(
            "Usage:\n"
            "  `/paid <bill_id>`     — e.g. `/paid 3`\n"
            "  `/paid <bank> <MM>`   — e.g. `/paid hdfc 05`",
            parse_mode="Markdown",
        )
        return

    # Try bill_id first (single numeric arg)
    if len(context.args) == 1 and context.args[0].isdigit():
        bill_id = int(context.args[0])
        bill = db.get_bill(bill_id)
        if not bill:
            await update.message.reply_text(f"No bill with ID `{bill_id}`.")
            return
        if bill["status"] == "paid":
            await update.message.reply_text(f"Bill #{bill_id} is already paid.")
            return
        db.mark_bill_paid(bill_id)
        await update.message.reply_text(
            f"✅ Marked bill #{bill_id} ({bill.get('card_name', bill['bank_key'])} — ₹{bill['amount']:,.2f}) as paid."
        )
        return

    # Try bank + month
    if len(context.args) == 2:
        bank_key = context.args[0].lower()
        month = context.args[1]
        bill = db.get_pending_by_bank_month(bank_key, month)
        if not bill:
            await update.message.reply_text(
                f"No pending bill for *{bank_key.upper()}* in month `{month}`."
            )
            return
        db.mark_bill_paid(bill["id"])
        await update.message.reply_text(
            f"✅ Marked bill #{bill['id']} ({bill.get('card_name', bank_key)} — ₹{bill['amount']:,.2f}) as paid."
        )
        return

    await update.message.reply_text("Invalid format. See `/paid` for help.")


async def forcecheck_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔍 Running scan now...")
    try:
        summary = daily_run()
        text = (
            f"Scan complete.\n"
            f"Processed: {summary.get('processed', 0)}\n"
            f"Reminded: {summary.get('reminded', 0)}\n"
            f"Failures: {summary.get('failures', 0)}"
        )
        await update.message.reply_text(text)
    except Exception as exc:
        await update.message.reply_text(f"Error during scan: {exc}")


async def teach_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /teach axis due:25-05-2026 amount:45320 stmt:15-05-2026 cycle:15Apr-14May card:"Axis Flipkart" mask:XXXX-1234
    """
    if not context.args:
        await update.message.reply_text(
            "Usage: `/teach <bank> due:DD-MM-YYYY amount:XXXX stmt:DD-MM-YYYY cycle:XX card:Name mask:XXXX-1234`"
        )
        return

    bank_key = context.args[0].lower()
    rest = " ".join(context.args[1:])

    parsed = _parse_teach_args(rest)
    if not parsed.get("due_date") or not parsed.get("amount"):
        await update.message.reply_text("Need at least `due:` and `amount:`.")
        return

    # Retrieve latest failed parse for this bank to get raw text
    fp = db.get_latest_failed_parse(bank_key)
    raw_text = fp["raw_text"] if fp else ""

    generate_patterns_from_teach(bank_key, raw_text, parsed)

    # Also resolve the failed parse
    if fp:
        db.resolve_failed_parse(fp["id"])

    # If we have enough info, store the bill too
    db.save_bill(
        {
            "bank_key": bank_key,
            "card_name": parsed.get("card"),
            "card_mask": parsed.get("mask"),
            "statement_date": parsed.get("stmt"),
            "due_date": parsed.get("due_date"),
            "amount": parsed.get("amount"),
            "bill_cycle": parsed.get("cycle"),
            "pdf_path": fp["pdf_path"] if fp else "",
            "status": "pending",
        }
    )

    await update.message.reply_text(
        f"🧠 Learned {len(parsed)} fields for *{bank_key.upper()}*. Next statement will be parsed automatically."
    )


async def confirm_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirm LLM guess and auto-learn."""
    if not context.args:
        await update.message.reply_text("Usage: `/confirm <bank> due:XX amount:XX ...`")
        return
    bank_key = context.args[0].lower()
    rest = " ".join(context.args[1:])
    parsed = _parse_teach_args(rest)

    fp = db.get_latest_failed_parse(bank_key)
    raw_text = fp["raw_text"] if fp else ""

    # Mark as human-confirmed (high confidence)
    generate_patterns_from_teach(bank_key, raw_text, parsed)
    if fp:
        db.resolve_failed_parse(fp["id"])

    db.save_bill(
        {
            "bank_key": bank_key,
            "card_name": parsed.get("card"),
            "card_mask": parsed.get("mask"),
            "statement_date": parsed.get("stmt"),
            "due_date": parsed.get("due_date"),
            "amount": parsed.get("amount"),
            "bill_cycle": parsed.get("cycle"),
            "pdf_path": fp["pdf_path"] if fp else "",
            "status": "pending",
        }
    )

    await update.message.reply_text(
        f"✅ Confirmed and learned for *{bank_key.upper()}*."
    )


async def patterns_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: `/patterns <bank>`")
        return
    bank_key = context.args[0].lower()
    patterns = db.get_patterns(bank_key)
    if not patterns:
        await update.message.reply_text(f"No patterns yet for *{bank_key.upper()}*.")
        return
    lines = [f"🔧 Patterns for *{bank_key.upper()}*"]
    for p in patterns:
        lines.append(
            f"• `{p['field']}` ({p['pattern_type']}) conf={p['confidence']:.2f} succ={p['success_count']}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: `/history <bank>`")
        return
    bank_key = context.args[0].lower()
    bills = db.get_bill_history(bank_key, limit=5)
    if not bills:
        await update.message.reply_text(f"No history for *{bank_key.upper()}*.")
        return
    lines = [f"📜 Recent bills — *{bank_key.upper()}*"]
    for b in bills:
        status = "✅" if b["status"] == "paid" else "⏳"
        lines.append(
            f"{status} {b.get('statement_date','?')} → ₹{b.get('amount','?')} (due {b.get('due_date','?')})"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def my_cards_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all registered cards for this user."""
    chat_id = str(update.effective_chat.id)
    cards = db.get_registered_cards(user_chat_id=chat_id)
    if not cards:
        await update.message.reply_text(
            "No cards registered yet. Use `/register` to add one."
        )
        return
    lines = ["💳 *Your Registered Cards*"]
    for c in cards:
        nick = c.get("card_nickname") or f"{c['bank_key'].upper()} Card"
        name = c["cardholder_name"]
        last4 = c["last_4_digits"]
        hint = c.get("password_hint") or "auto"
        lines.append(
            f"`#{c['id']}` *{nick}*\n"
            f"   Name: {name} | Last 4: {last4}\n"
            f"   Bank: {c['bank_key'].upper()} | Password hint: `{hint}`"
        )
    await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")


# ── Registration wizard (ConversationHandler) ─────

REG_BANK, REG_NAME, REG_LAST4, REG_NICK, REG_PW = range(5)

async def register_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start card registration."""
    banks = sorted(BANK_SENDERS.keys())
    keyboard = [
        [InlineKeyboardButton(bk.upper(), callback_data=f"reg_bank:{bk}")]
        for bk in banks
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Select your bank:", reply_markup=reply_markup
    )
    return REG_BANK


async def reg_bank_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    bank_key = query.data.split(":")[1]
    context.user_data["reg_bank"] = bank_key
    await query.edit_message_text(
        f"Bank: *{bank_key.upper()}*\n\nNow send the cardholder name as it appears on the card:"
    )
    return REG_NAME


async def reg_name_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["reg_name"] = update.message.text.strip()
    await update.message.reply_text(
        "Got it. Now send the *last 4 digits* of the card number:"
    )
    return REG_LAST4


async def reg_last4_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    last4 = update.message.text.strip()
    if not last4.isdigit() or len(last4) != 4:
        await update.message.reply_text("Please send exactly 4 digits.")
        return REG_LAST4
    context.user_data["reg_last4"] = last4
    await update.message.reply_text(
        "Great! (Optional) Send a nickname for this card, or type `skip`:"
    )
    return REG_NICK


async def reg_nick_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    nick = update.message.text.strip()
    if nick.lower() == "skip":
        nick = None
    context.user_data["reg_nick"] = nick

    bank_key = context.user_data["reg_bank"]
    # Show password preview
    preview = generate_pdf_password(
        bank_key,
        context.user_data["reg_name"],
        context.user_data["reg_last4"],
    )
    await update.message.reply_text(
        f"Suggested PDF password for *{bank_key.upper()}*: `{preview}`\n\n"
        f"If this is correct, type `ok`.\n"
        f"If your bank uses a different pattern, type it now using placeholders:\n"
        f"  `{{first4}}{{last4}}`  →  RAJE1234\n"
        f"  `{{last4}}`  →  1234\n"
        f"Or just type your exact password:",
        parse_mode="Markdown",
    )
    return REG_PW


async def reg_pw_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    chat_id = str(update.effective_chat.id)
    bank_key = context.user_data["reg_bank"]
    name = context.user_data["reg_name"]
    last4 = context.user_data["reg_last4"]
    nick = context.user_data.get("reg_nick")

    if text.lower() == "ok":
        password_hint = None  # use bank default
    else:
        password_hint = text

    db.register_card(chat_id, bank_key, name, last4, nick, password_hint)
    await update.message.reply_text(
        f"✅ Card registered!\n"
        f"   Bank: *{bank_key.upper()}*\n"
        f"   Name: {name}\n"
        f"   Last 4: {last4}\n"
        f"   Nickname: {nick or '—'}\n\n"
        f"When a statement email arrives, I'll use this info to unlock the PDF.",
        parse_mode="Markdown",
    )
    context.user_data.clear()
    return ConversationHandler.END


async def reg_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Registration cancelled.")
    context.user_data.clear()
    return ConversationHandler.END


async def delete_card_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: `/delete_card <id>`\nSee IDs with `/my_cards`")
        return
    try:
        card_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Please provide a numeric card ID.")
        return
    db.delete_registered_card(card_id)
    await update.message.reply_text(f"🗑️ Deleted card #{card_id}.")


async def upload_pdf_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle PDF uploads from user (e.g. AMEX statements downloaded manually).
    Detects bank from registered cards or filename, tries to parse.
    """
    document = update.message.document
    if not document or not document.file_name.lower().endswith(".pdf"):
        await update.message.reply_text("Please send a PDF file.")
        return

    chat_id = str(update.effective_chat.id)
    cards = db.get_registered_cards(user_chat_id=chat_id)

    # Try to infer bank from filename or registered cards conversation
    bank_key = context.user_data.get("upload_bank")
    if not bank_key and cards:
        # If only one card registered, assume that bank
        if len(cards) == 1:
            bank_key = cards[0]["bank_key"]
        else:
            await update.message.reply_text(
                "You have multiple cards. Please specify the bank first by sending: `bank:axis` (or hdfc, icici, etc.)"
            )
            context.user_data["pending_pdf"] = True
            return

    if not bank_key:
        await update.message.reply_text(
            "Please register a card first with `/register`, or specify the bank."
        )
        return

    # Download the PDF
    file = await context.bot.get_file(document.file_id)
    tmp_dir = Path(tempfile.gettempdir()) / "kreditkard_uploads"
    tmp_dir.mkdir(exist_ok=True)
    dest = tmp_dir / f"{chat_id}_{document.file_name}"
    await file.download_to_drive(dest)

    await update.message.reply_text(f"📄 Received {document.file_name}. Parsing...")

    # Try passwords
    bank_cards = [c for c in cards if c["bank_key"] == bank_key]
    raw_text = None

    # Try without password first
    try:
        raw_text = extract_text(dest)
    except Exception:
        pass

    # Try each registered card's password
    if raw_text is None:
        for card in bank_cards:
            pw = generate_pdf_password(
                bank_key, card["cardholder_name"], card["last_4_digits"], card.get("password_hint")
            )
            try:
                raw_text = extract_text(dest, password=pw)
                break
            except Exception:
                continue

    if raw_text is None:
        await update.message.reply_text(
            "❌ Could not open the PDF. Is it password-protected? "
            "Make sure you've registered the card with the correct password hint."
        )
        return

    # Parse
    parsed = parse_statement(bank_key, raw_text)
    method = "pattern"
    if not parsed:
        parsed = llm_fallback(bank_key, raw_text)
        method = "llm"
        if parsed:
            auto_save_patterns_from_llm(bank_key, raw_text, parsed)
    if not parsed:
        parsed = heuristic_fallback(bank_key, raw_text)
        method = "heuristic"

    if not parsed:
        await update.message.reply_text(
            "⚠️ Could not parse this statement automatically.\n\n"
            f"You can teach me with:\n"
            f"`/teach {bank_key} due:DD-MM-YYYY amount:XXXX stmt:DD-MM-YYYY`"
        )
        # Save snippet for teach command
        from llm_client import parse_with_llm_for_amount_due
        llm_guess = parse_with_llm_for_amount_due(raw_text)
        db.save_failed_parse(bank_key, raw_text, str(dest), llm_guess)
        return

    # Save bill
    from main import _match_to_registered_card, _save_parsed_bill
    summary = {"new_bills": 0}
    _save_parsed_bill(bank_key, parsed, pdf_path=str(dest), summary=summary)

    card_name = parsed.get("card_name") or bank_key.upper()
    due = parsed.get("due_date", "?")
    amt = parsed.get("amount")
    await update.message.reply_text(
        f"✅ Parsed via *{method}*!\n"
        f"Card: *{card_name}*\n"
        f"Due: `{due}`\n"
        f"Amount: *₹{amt:,.2f}*\n\n"
        f"Bill saved. Reply `/status` to see all pending dues.",
        parse_mode="Markdown",
    )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Catch bank hints like 'bank:axis' when a PDF is pending."""
    text = update.message.text.strip().lower()
    if context.user_data.get("pending_pdf") and text.startswith("bank:"):
        bank_key = text.split(":")[1].strip()
        if bank_key in BANK_SENDERS:
            context.user_data["upload_bank"] = bank_key
            context.user_data.pop("pending_pdf", None)
            await update.message.reply_text(
                f"Got it. Now send the PDF for *{bank_key.upper()}*.", parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(f"Unknown bank: `{bank_key}`")
        return

    # Default: echo help
    await update.message.reply_text(
        "I didn't understand that. Send a PDF to parse a statement, or use /help."
    )


def _parse_teach_args(text: str) -> dict:
    """Parse key:value pairs from teach/confirm command text."""
    result: dict = {}
    # Regex to capture key:value or key:"value with spaces"
    for m in re.finditer(r'(\w+):("[^"]+"|[^\s]+)', text):
        key = m.group(1).lower()
        val = m.group(2).strip('"')
        if key in ("due", "due_date"):
            result["due_date"] = val
        elif key in ("amount", "amt"):
            result["amount"] = val
        elif key in ("stmt", "statement_date"):
            result["stmt"] = val
        elif key == "cycle":
            result["cycle"] = val
        elif key in ("card", "card_name"):
            result["card"] = val
        elif key in ("mask", "card_mask"):
            result["mask"] = val
    return result


def _days_left(due_str: str | None) -> str:
    if not due_str:
        return "?"
    try:
        due = datetime.strptime(due_str[:10], "%Y-%m-%d")
        delta = (due - datetime.utcnow()).days
        return str(delta)
    except Exception:
        return "?"


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Registration conversation
    reg_conv = ConversationHandler(
        entry_points=[CommandHandler("register", register_cmd)],
        states={
            REG_BANK: [CallbackQueryHandler(reg_bank_callback, pattern=r"^reg_bank:")],
            REG_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_name_msg)],
            REG_LAST4: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_last4_msg)],
            REG_NICK: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_nick_msg)],
            REG_PW: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_pw_msg)],
        },
        fallbacks=[CommandHandler("cancel", reg_cancel)],
    )

    app.add_handler(reg_conv)
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("my_cards", my_cards_cmd))
    app.add_handler(CommandHandler("delete_card", delete_card_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("paid", paid_cmd))
    app.add_handler(CommandHandler("forcecheck", forcecheck_cmd))
    app.add_handler(CommandHandler("teach", teach_cmd))
    app.add_handler(CommandHandler("confirm", confirm_cmd))
    app.add_handler(CommandHandler("patterns", patterns_cmd))
    app.add_handler(CommandHandler("history", history_cmd))

    # PDF upload handler
    app.add_handler(MessageHandler(filters.Document.PDF, upload_pdf_handler))
    # Catch-all text handler (for bank hints etc)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("Bot polling... Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
