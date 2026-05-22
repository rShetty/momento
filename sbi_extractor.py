"""SBI Card credit card statement specific extractor.

Handles common SBI Card statement layouts where:
  - Labels and values may be inline or in vertical tables
  - Amounts prefixed with ₹ / Rs.
  - Dates in DD MMM YYYY or DD/MM/YYYY format
  - Card masks: XXXX XXXX XXXX 1234 or XXXX-XXXX-XXXX-1234
  - Password is often just last 4 digits or DOB
"""

import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from utils import (
    parse_date,
    parse_amount,
    extract_card_masks,
    extract_bill_cycle,
    extract_dates,
    extract_amounts,
    extract_next_line_value,
    lines_around,
)


# SBI-specific keyword variations
_SBI_AMOUNT_LABELS = [
    "total amount due",
    "total outstanding",
    "amount due",
    "payment due",
    "total payment due",
    "current outstanding",
    "total dues",
    "amount payable",
]

_SBI_DUE_DATE_LABELS = [
    "payment due date",
    "due date",
    "payment due by",
    "last date for payment",
    "pay by",
    "payment due",
]

_SBI_STATEMENT_DATE_LABELS = [
    "statement date",
    "date of statement",
    "statement generated on",
]

_SBI_CYCLE_LABELS = [
    "statement period",
    "billing period",
    "bill cycle",
]


def parse_sbi_statement(raw_text: str) -> dict[str, Any] | None:
    """
    Extract all fields from an SBI Card credit card statement.
    Returns a dict with at least due_date and amount on success.
    """
    lines = raw_text.splitlines()
    result: dict[str, Any] = {"bank_key": "sbi"}

    # ── 1. Amount ───────────────────────────────
    for label in _SBI_AMOUNT_LABELS:
        val = extract_next_line_value(raw_text, label)
        if val:
            amt = parse_amount(val)
            if amt:
                result["amount"] = amt
                break
    if "amount" not in result:
        for label in _SBI_AMOUNT_LABELS:
            snippet = lines_around(raw_text, label, window=3)
            if snippet:
                amts = extract_amounts("\n".join(snippet))
                if amts:
                    result["amount"] = max(amts)
                    break

    # ── 2. Due Date ─────────────────────────────
    for label in _SBI_DUE_DATE_LABELS:
        val = extract_next_line_value(raw_text, label)
        if val:
            dt = parse_date(val)
            if dt:
                result["due_date"] = dt
                break
    if "due_date" not in result:
        for label in _SBI_DUE_DATE_LABELS:
            snippet = lines_around(raw_text, label, window=3)
            if snippet:
                dates = extract_dates("\n".join(snippet))
                if dates:
                    result["due_date"] = dates[0]
                    break

    # ── 3. Statement Date ───────────────────────
    for label in _SBI_STATEMENT_DATE_LABELS:
        val = extract_next_line_value(raw_text, label)
        if val:
            dt = parse_date(val)
            if dt:
                result["statement_date"] = dt
                break
    if "statement_date" not in result:
        for label in _SBI_STATEMENT_DATE_LABELS:
            snippet = lines_around(raw_text, label, window=3)
            if snippet:
                dates = extract_dates("\n".join(snippet))
                if dates:
                    result["statement_date"] = dates[0]
                    break

    # ── 4. Bill Cycle ───────────────────────────
    for label in _SBI_CYCLE_LABELS:
        snippet = lines_around(raw_text, label, window=2)
        if snippet:
            cyc = extract_bill_cycle("\n".join(snippet))
            if cyc:
                result["bill_cycle"] = cyc
                break
    if "bill_cycle" not in result:
        # SBI format: "Statement Period: 18 Mar, 2026 to 17 Apr, 2026"
        m = re.search(
            r"statement\s*period[:\s]*(\d{1,2}\s+[A-Za-z]{3},?\s*\d{4})\s*[-–to]+\s*(\d{1,2}\s+[A-Za-z]{3},?\s*\d{4})",
            raw_text,
            re.IGNORECASE,
        )
        if m:
            result["bill_cycle"] = f"{m.group(1)} to {m.group(2)}"

    # ── 5. Card Mask ────────────────────────────
    masks = extract_card_masks(raw_text)
    if masks:
        result["card_mask"] = masks[0]
    # SBI-specific: "Card No.: XXXX XXXX XXXX 1234"
    if "card_mask" not in result:
        m = re.search(
            r"card\s*no\.?[:\s]*((?:[x*•]{4}[\s-]*){3}\d{4})",
            raw_text,
            re.IGNORECASE,
        )
        if m:
            result["card_mask"] = m.group(1)

    # ── 6. Card Name ────────────────────────────
    for line in lines:
        if "sbi" in line.lower() and "credit card" in line.lower():
            result["card_name"] = line.strip()
            break

    # Validate minimum required fields
    if result.get("due_date") and result.get("amount"):
        return result
    return None
