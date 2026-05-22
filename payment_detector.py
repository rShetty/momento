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
    "alerts@hdfcbank.bank.in",
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
    Handles: ending 3464, ending **3464, XX5682, XXXX-XXXX-XXXX-1234, •••• 2916
    """
    text = text.lower()
    patterns = [
        r"ending\s*\*?\*?\s*(\d{4})",
        r"\*\*(\d{4})",
        r"xx(\d{4})",
        r"xxxx-xxxx-xxxx-(\d{4})",
        r"[•*]{2,}\s*(\d{4})",
        r"card\s+ending\s+(\d{4})",
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
        subject_lower = subject.lower()
        
        # ── Skip obvious non-payment emails ──
        # Skip HDFC purchase alerts (not bill payments)
        if "a payment was made using your credit card" in subject_lower:
            continue
        
        # Skip UPI transaction alerts (these are purchases, not bill payments)
        if "you have done a upi txn" in subject_lower:
            continue
        if "credited to vpa" in lower_text and "debited from your" in lower_text:
            continue
        
        # Skip statement notifications masquerading as payments
        statement_subj_kws = ["new statement", "statement is here", "statement generated", 
                              "view your statement", "smart statement", "bill summary"]
        payment_subj_kws = ["payment successful", "payment confirmed", "payment received",
                            "thank you for your payment", "auto debit", "mandate"]
        has_stmt_subj = any(kw in subject_lower for kw in statement_subj_kws)
        has_pay_subj = any(kw in subject_lower for kw in payment_subj_kws)
        if has_stmt_subj and not has_pay_subj:
            continue
        
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
        
        # Find pending bills matching last4, prefer most recent statement
        matching_bills = [b for b in pending_bills if last4 in (b.get("card_mask") or "")]
        if matching_bills:
            matching_bills.sort(key=lambda b: b.get("statement_date") or "", reverse=True)
            matched_bill = matching_bills[0]
        
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
        
        # Check for payment vs statement signals
        payment_keywords = ["payment received", "payment successful", "thank you for your payment", 
                           "payment confirmed", "paid successfully", "credited to your card",
                           "payment of rs", "payment of ₹", "auto debit", "debited"]
        statement_keywords = ["new statement", "statement is ready", "view your statement", 
                             "statement generated", "statement period", "statement date",
                             "your statement"]
        
        has_payment_kw = any(kw in lower_text for kw in payment_keywords)
        has_statement_kw = any(kw in lower_text for kw in statement_keywords)
        
        # Amount exact match → medium confidence (not enough alone)
        bill_amount = matched_bill.get("amount")
        amount_match = False
        if amount and bill_amount:
            bill_amt = Decimal(str(bill_amount))
            if abs(amount - bill_amt) < Decimal("1.00"):
                amount_match = True
                reason_parts.append(f"exact_amount=₹{amount}")
        
        # CRED payee → medium confidence (not enough alone, CRED sends both statements and payments)
        is_cred = payee and "cred" in payee.lower()
        if is_cred:
            reason_parts.append("payee=CRED")
        
        # High confidence ONLY if:
        # 1. Has payment keywords AND no statement keywords, OR
        # 2. Amount match + explicit payment confirmation (not just statement notification)
        if has_payment_kw and not has_statement_kw:
            confidence = "high"
            reason_parts.append("keywords=payment_confirmed")
        elif amount_match and is_cred and not has_statement_kw:
            # CRED payment without statement keywords
            confidence = "high"
            reason_parts.append("cred_payment")
        elif has_statement_kw:
            # This is likely a statement notification, not a payment
            confidence = "low"
            reason_parts.append("keywords=statement_not_payment")
        elif amount_match:
            # Amount matches but no payment confirmation keywords
            confidence = "medium"
            reason_parts.append("amount_match_no_payment_kw")
        
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
        
        # Skip if already paid/superseded
        if matched_bill.get("status") != "pending":
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
