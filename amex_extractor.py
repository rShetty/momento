"""AMEX credit card statement extractor.

AMEX sends a notification email with a link to the statement.
This extractor tries to parse the email body for inline summary data.
If the email text doesn't contain enough info, it signals that a
manual PDF upload is needed.

Typical AMEX email body includes:
  - "Total Amount Due: ₹X,XXX.XX" or "Amount Due: ₹X,XXX"
  - "Payment Due Date: DD MMM YYYY" or "Please pay by DD MMM YYYY"
  - Statement period info
"""

import re
from decimal import Decimal
from typing import Any

from utils import parse_date, parse_amount, extract_dates, extract_amounts, extract_card_masks


_AMEX_AMOUNT_LABELS = [
    "total amount due",
    "amount due",
    "payment due",
    "total payment due",
    "current balance",
    "new balance",
]

_AMEX_DUE_DATE_LABELS = [
    "payment due date",
    "due date",
    "payment due by",
    "please pay by",
    "pay by",
]


def parse_amex_email(raw_text: str) -> dict[str, Any] | None:
    """
    Try to extract bill data from an AMEX notification email body.
    Returns a dict with at least due_date and amount, or None if not enough info.
    """
    result: dict[str, Any] = {"bank_key": "amex"}

    # ── 1. Amount ───────────────────────────────
    for label in _AMEX_AMOUNT_LABELS:
        m = re.search(
            rf"{re.escape(label)}[\s:]*([₹Rs.\s]*[\d,]+\.\d{{2}})",
            raw_text, re.IGNORECASE,
        )
        if m:
            amt = parse_amount(m.group(1))
            if amt:
                result["amount"] = amt
                break
    if "amount" not in result:
        amts = extract_amounts(raw_text)
        if amts:
            result["amount"] = amts[0]

    # ── 2. Due Date ─────────────────────────────
    for label in _AMEX_DUE_DATE_LABELS:
        m = re.search(
            rf"{re.escape(label)}[\s:]*(\d{{1,2}}\s+[A-Za-z]{{3}}[,\s]*\d{{4}})",
            raw_text, re.IGNORECASE,
        )
        if m:
            dt = parse_date(m.group(1))
            if dt:
                result["due_date"] = dt
                break
    if "due_date" not in result:
        dates = extract_dates(raw_text)
        if dates:
            result["due_date"] = dates[0]

    # ── 3. Statement Date ───────────────────────
    dates = extract_dates(raw_text)
    if len(dates) >= 2:
        # Usually statement date is earlier than due date
        result["statement_date"] = min(dates[0], dates[1])
    elif dates:
        result["statement_date"] = dates[0]

    # ── 4. Card Mask ────────────────────────────
    masks = extract_card_masks(raw_text)
    if masks:
        result["card_mask"] = masks[0]

    # ── 5. Card Name ────────────────────────────
    if "american express" in raw_text.lower():
        result["card_name"] = "American Express"

    # Validate minimum required fields
    if result.get("due_date") and result.get("amount"):
        return result
    return None
