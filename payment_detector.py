"""
Payment confirmation email detector — bank-agnostic.

Handles:
  • CRED payments (protect@cred.club, support@cred.club)
  • Any bank debit alert (HDFC, Axis, ICICI, SBI, etc.)
  • UPI / NEFT / IMPS payment confirmations
  • Statement payment / auto-debit emails

Strategy:
  1. Scan emails from any known bank sender or cred.club
  2. Extract last-4 digits + amount + payee/bank from each email
  3. Match to pending bills by last-4 → verify with exact amount
"""

import re
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta

import db
from gmail_client import fetch_emails_by_query, fetch_email_body_text

# ── Config ──────────────────────────────────────
PAYMENT_QUERY_DAYS = 14

# Bank sender domains to check for debit alerts
BANK_ALERT_DOMAINS = [
    "alerts@hdfcbank.net",
    "alerts@axisbank.com",
    "alerts@icicibank.com",
    "onlinesbi@sbi.co.in",
    "alerts@kotak.com",
    "alerts@indusind.com",
    "statements@rblbank.com",
    "alerts@citi.com",
    "alerts@amex.com",
]

def _extract_amount(text: str) -> Decimal | None:
    """Extract the first plausible amount from text (₹ or Rs. or just digits + commas)."""
    # Try common amount patterns
    patterns = [
        r"Rs\.?\s*([\d,]+\.\d{2})",
        r"₹\s*([\d,]+\.\d{2})",
        r"INR\s*([\d,]+\.\d{2})",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            try:
                return Decimal(m.group(1).replace(",", ""))
            except (InvalidOperation, ValueError):
                pass
    return None


def _extract_last4(text: str) -> str | None:
    """
    Extract card last-4 digits from debit / payment emails.
    Handles: ending 3464, **3464, XX5682, XXXX-XXXX-XXXX-1234, •••• 2916
    """
    text = text.lower()
    patterns = [
        r"ending\s*(?:\*\*)?(\d{4})",
        r"\*\*(\d{4})",
        r"xx(\d{4})",
        r"xxxx-xxxx-xxxx-(\d{4})",
        r"[•*]{2,}\s*(\d{4})",
        r"card.{0,15}(\d{4})(?:\D|$)",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1)
    return None


def _extract_payee(text: str) -> str | None:
    """Try to extract payee / beneficiary name from UPI or payment text."""
    text = text.lower()
    # UPI payee: to VPA xxx@xxx NAME
    m = re.search(r"to\s+vpa\s+[^\s]+\s+([a-z .]+)", text)
    if m:
        return m.group(1).strip()
    # CRED pattern
    if "cred.club" in text or "cred club" in text:
        return "CRED"
    # Generic: towards / to  [Merchant Name]
    m = re.search(r"(?:towards|to)\s+([a-z*][a-z0-9* ]{2,40})", text)
    if m:
        return m.group(1).strip()
    return None


def detect_payments() -> list[dict]:
    """
    Scan Gmail for payment confirmations and auto-mark matching bills as paid.
    Returns a list of actions taken for diagnostics.
    """
    since = (datetime.utcnow() - timedelta(days=PAYMENT_QUERY_DAYS)).strftime("%Y/%m/%d")
    
    # Query covers: bank alerts, CRED emails, and generic payment keywords
    sender_queries = [f"from:{s}" for s in BANK_ALERT_DOMAINS]
    query = (
        f"({' OR '.join(sender_queries)} OR from:cred.club) "
        f"after:{since}"
    )
    
    emails = fetch_emails_by_query(query, max_results=100)
    if not emails:
        return []
    
    actions: list[dict] = []
    pending_bills = db.get_pending_bills()
    registered_cards = db.get_registered_cards()
    
    for email in emails:
        sender = email.get("sender", "").lower()
        subject = email.get("subject", "")
        snippet = email.get("snippet", "")
        
        # Fetch body for deeper parsing
        body = ""
        try:
            body = fetch_email_body_text(email["id"])
        except Exception:
            pass
        
        full_text = f"{subject}\n{snippet}\n{body}"
        lower_text = full_text.lower()
        
        # Extract universal fields
        last4 = _extract_last4(full_text)
        amount = _extract_amount(full_text)
        payee = _extract_payee(lower_text)
        
        if not last4:
            continue  # Can't match without a card identifier
        
        # ── Try to match against a pending bill ──
        matched_bill = None
        matched_card = None
        
        # Find card registration by last4
        for card in registered_cards:
            if card["last_4_digits"] == last4:
                matched_card = card
                break
        
        # Find pending bill by card_mask containing last4
        for bill in pending_bills:
            mask = bill.get("card_mask") or ""
            if last4 in mask:
                matched_bill = bill
                break
        
        if not matched_bill and matched_card:
            # Fallback: match by bank + card nickname
            for bill in pending_bills:
                nick = matched_card.get("card_nickname", "")
                name = bill.get("card_name", "")
                if nick and nick in name:
                    matched_bill = bill
                    break
        
        if not matched_bill:
            continue
        
        # ── Confidence scoring ──
        confidence = "low"
        reason_parts = [f"last4={last4}"]
        
        # Amount exact match → high confidence
        bill_amount = matched_bill.get("amount")
        if amount and bill_amount:
            bill_amt = Decimal(str(bill_amount))
            if abs(amount - bill_amt) < Decimal("1.00"):
                confidence = "high"
                reason_parts.append(f"exact_amount=₹{amount}")
        
        # CRED payee → high confidence
        if payee and "cred" in payee.lower():
            confidence = "high"
            reason_parts.append("payee=CRED")
        
        # Keywords in text → bump confidence
        keywords = ["bill payment", "credit card bill", "outstanding", "total amount due"]
        if any(kw in lower_text for kw in keywords):
            confidence = "high"
            reason_parts.append("keywords=bill_payment")
        
        # Only auto-mark if confidence is high
        if confidence != "high":
            actions.append(
                {
                    "bill_id": matched_bill["id"],
                    "action": "skipped_low_confidence",
                    "last4": last4,
                    "amount": str(amount) if amount else None,
                    "payee": payee,
                }
            )
            continue
        
        # Mark as paid
        db.mark_bill_paid(matched_bill["id"])
        actions.append(
            {
                "bill_id": matched_bill["id"],
                "bank_key": matched_bill["bank_key"],
                "action": "marked_paid",
                "trigger": subject[:60],
                "source": "cred" if (payee and "cred" in payee.lower()) else "bank_debit",
                "card": matched_bill.get("card_name", matched_bill["bank_key"]),
                "reason": " | ".join(reason_parts),
            }
        )
    
    return actions
