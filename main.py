"""Main daily entry point for cron."""

from datetime import datetime
from pathlib import Path

from config import PDF_DIR, READ_EMAIL_DAYS_BACK, all_senders, bank_for_sender, generate_pdf_password
from db import init_db, save_bill, save_failed_parse, bill_exists, get_registered_cards, get_registered_card_by_mask, supersede_old_bills
from gmail_client import fetch_statement_emails, download_pdf
from pdf_extractor import extract_text
from pattern_matcher import parse_statement, llm_fallback, heuristic_fallback
from pattern_generator import auto_save_patterns_from_llm
from payment_detector import detect_payments
from reminder import remind_pending, notify_failure, notify_daily_summary, notify_upload_needed


def _try_passwords(pdf_path: Path, bank_key: str) -> str | None:
    """Try to extract PDF text using registered card passwords."""
    cards = get_registered_cards()
    bank_cards = [c for c in cards if c["bank_key"] == bank_key]

    # Try without password first
    try:
        return extract_text(pdf_path)
    except Exception:
        pass

    # Try each registered card's password
    for card in bank_cards:
        pw = generate_pdf_password(
            bank_key,
            card["cardholder_name"],
            card["last_4_digits"],
            card.get("password_hint"),
        )
        try:
            return extract_text(pdf_path, password=pw)
        except Exception:
            continue

    return None


def _match_to_registered_card(bank_key: str, parsed: dict) -> dict | None:
    """Match parsed statement to a registered card by last-4 digits."""
    mask = parsed.get("card_mask")
    if not mask:
        return None
    return get_registered_card_by_mask(bank_key, mask)


def daily_run() -> dict:
    """
    One full end-to-end run:
      1. Fetch statement emails (PDF + link-based)
      2. Download PDFs (try passwords from registered cards)
      3. Parse / learn
      4. Match to registered cards
      5. Detect payments
      6. Send reminders
      7. Daily summary
    Returns a summary dict.
    """
    init_db()

    summary = {
        "processed": 0,
        "new_bills": 0,
        "failures": 0,
        "reminded": 0,
        "paid_detected": 0,
    }

    # ── 1. Gmail scan ────────────────────────────
    senders = all_senders()
    emails = fetch_statement_emails(senders, days_back=READ_EMAIL_DAYS_BACK)
    print(f"[main] Found {len(emails)} statement emails.")

    for email in emails:
        summary["processed"] += 1
        bank_key = bank_for_sender(email["sender"])
        if not bank_key:
            print(f"[main] Unknown sender: {email['sender']}; skipping.")
            continue

        # ── 1a. Link-based (no attachment) ────────
        if not email["attachments"]:
            if bank_key == "amex":
                parsed = _try_parse_link_email(bank_key, email)
                if parsed:
                    _save_parsed_bill(bank_key, parsed, pdf_path="", summary=summary)
                    continue
                else:
                    # Ask user to upload PDF manually
                    notify_upload_needed(bank_key, email)
                    continue
            else:
                print(f"[main] No attachments for {bank_key}; skipping.")
                continue

        # ── 1b. PDF attachments ───────────────────
        for att in email["attachments"]:
            dest = PDF_DIR / bank_key / f"{email['id']}_{att['filename']}"
            pdf = download_pdf(email["id"], att["attachment_id"], dest)
            if not pdf:
                continue

            # ── 2. Extract text (try passwords) ─────
            raw_text = _try_passwords(pdf, bank_key)
            if raw_text is None:
                print(f"[main] Could not open PDF for {bank_key} (tried all registered passwords)")
                continue

            # ── 3. Parse logic ──────────────────────
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
                summary["failures"] += 1
                llm_guess = None
                from llm_client import parse_with_llm_for_amount_due
                llm_guess = parse_with_llm_for_amount_due(raw_text)
                save_failed_parse(bank_key, raw_text, str(pdf), llm_guess)
                notify_failure(bank_key, str(pdf), raw_text[:600], llm_guess)
                continue

            _save_parsed_bill(bank_key, parsed, pdf_path=str(pdf), summary=summary)

    # ── 5. Payment detection ─────────────────────
    payment_actions = detect_payments()
    summary["paid_detected"] = len(payment_actions)
    for a in payment_actions:
        print(f"[main] Payment detected: {a}")

    # ── 6. Reminders ─────────────────────────────
    reminders = remind_pending()
    summary["reminded"] = len(reminders)
    for r in reminders:
        print(f"[main] Reminder sent: {r}")

    # ── 7. Summary ───────────────────────────────
    notify_daily_summary(
        summary["processed"],
        summary["reminded"],
        summary["paid_detected"],
        summary["failures"],
    )

    return summary


def _try_parse_link_email(bank_key: str, email: dict) -> dict | None:
    """For link-based emails (AMEX), try to parse the body text."""
    raw_text = email.get("body_text", "")
    if bank_key == "amex":
        from amex_extractor import parse_amex_email
        return parse_amex_email(raw_text)
    return None


def _save_parsed_bill(bank_key: str, parsed: dict, pdf_path: str, summary: dict) -> None:
    """Save a successfully parsed bill to DB."""
    registered = _match_to_registered_card(bank_key, parsed)
    if registered:
        print(f"[main] Matched to registered card: {registered.get('card_nickname') or registered['cardholder_name']}")
        card_display_name = registered.get("card_nickname") or registered["cardholder_name"]
    else:
        card_display_name = parsed.get("card_name") or bank_key.upper()

    amount = parsed.get("amount")
    due_date = parsed.get("due_date")
    stmt_date = parsed.get("statement_date")

    due_iso = due_date.isoformat() if due_date else None
    stmt_iso = stmt_date.isoformat() if stmt_date else None

    if bill_exists(bank_key, stmt_iso, parsed.get("card_mask")):
        print(f"[main] Bill already exists for {bank_key}/{stmt_iso}; skipping")
        return

    bill = {
        "bank_key": bank_key,
        "card_name": card_display_name,
        "card_mask": parsed.get("card_mask"),
        "statement_date": stmt_iso,
        "due_date": due_iso,
        "amount": float(amount) if amount else None,
        "bill_cycle": parsed.get("bill_cycle"),
        "pdf_path": pdf_path,
        "status": "pending",
    }
    bill_id = save_bill(bill)
    summary["new_bills"] += 1
    supersede_old_bills(bank_key, parsed.get("card_mask"), bill_id)
    print(f"[main] Saved bill: {bill}")


if __name__ == "__main__":
    print("[main] KreditKard daily run starting...")
    result = daily_run()
    print("[main] Done.", result)
