"""Axis Bank credit card statement specific extractor.

Handles multiple Axis statement layouts:
  1. 2-column table (Atlas / newer): labels in left col, values in right col
  2. Simple vertical: label then value on next line
  3. Inline: label and value on same line

Axes formats seen:
  - DD/MM/YYYY dates (07/04/2026, 20/02/2026)
  - Card mask: 410038******7061
  - Amounts may be 0.00 (no bill)

The 2-column layout from PyMuPDF looks like:
    Total Payment Due
    Minimum Payment Due
    Statement Period
    Payment Due Date
    Statement Generation Date
    20/02/2026 - 18/03/2026
    07/04/2026
    18/03/2026
    0.00
    0.00
"""

import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from utils import parse_date, parse_amount, extract_card_masks, extract_bill_cycle


def _extract_payment_summary_block(lines: list[str]) -> dict[str, Any]:
    """
    Parse the Axis 2-column 'PAYMENT SUMMARY' block.
    Axis consistently puts this section after the name/address.
    Returns dict with amount/due_date/statement_date/bill_cycle if found.
    """
    result: dict[str, Any] = {}

    # Find the PAYMENT SUMMARY section
    start = None
    end = None
    for i, line in enumerate(lines):
        if "PAYMENT SUMMARY" in line.upper():
            start = i
        elif start is not None and "Credit Card Number" in line:
            end = i
            break

    if start is None:
        return result

    section = lines[start:end] if end else lines[start:]
    section_text = "\n".join(section)

    # Extract all dates in this section, in order of appearance
    date_matches = list(re.finditer(r"\b\d{1,2}/\d{1,2}/\d{4}\b", section_text))
    dates_in_order = []
    for m in date_matches:
        dt = parse_date(m.group(0))
        if dt:
            dates_in_order.append((m.group(0), dt))

    # Extract all amounts in this section, in order of appearance
    amount_matches = list(re.finditer(r"\b[\d,]+\.\d{2}\b", section_text))
    amounts_in_order = []
    for m in amount_matches:
        amt = parse_amount(m.group(0))
        if amt is not None:
            amounts_in_order.append((m.group(0), amt))

    # Bill cycle: usually the first date range in the section
    cycle_match = re.search(
        r"(\d{1,2}/\d{1,2}/\d{4})\s*[-–to]+\s*(\d{1,2}/\d{1,2}/\d{4})",
        section_text,
    )
    if cycle_match:
        result["bill_cycle"] = f"{cycle_match.group(1)} to {cycle_match.group(2)}"

    # In Axis 2-column layout, dates appear in this order:
    #   index 0 = cycle start
    #   index 1 = cycle end  
    #   index 2 = Payment Due Date
    #   index 3 = Statement Generation Date
    # (Sometimes cycle end === statement date if they're the same day)
    if len(dates_in_order) >= 4:
        result["due_date"] = dates_in_order[2][1]
        result["statement_date"] = dates_in_order[3][1]
    elif len(dates_in_order) == 3:
        result["due_date"] = dates_in_order[2][1]
        result["statement_date"] = dates_in_order[2][1]
    elif len(dates_in_order) >= 1:
        result["due_date"] = dates_in_order[0][1]
        result["statement_date"] = dates_in_order[0][1]

    # Amounts: in 2-column layout, the last two amounts are:
    #   -2 = Total Payment Due
    #   -1 = Minimum Payment Due
    # We need at least 2 amounts to distinguish them
    if len(amounts_in_order) >= 2:
        result["amount"] = amounts_in_order[-2][1]
    elif len(amounts_in_order) == 1:
        result["amount"] = amounts_in_order[0][1]

    return result


def _find_inline_value(text: str, label: str, value_pattern: str) -> str | None:
    """Look for label:value on the same line."""
    pattern = rf"{re.escape(label)}[\s:]*({value_pattern})"
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1) if m else None


def parse_axis_statement(raw_text: str) -> dict[str, Any] | None:
    """
    Extract all fields from an Axis credit card statement.
    Returns a dict with at least due_date and amount on success.
    """
    lines = raw_text.splitlines()
    result: dict[str, Any] = {"bank_key": "axis"}

    # ── Strategy 1: 2-column table (PAYMENT SUMMARY block) ──
    summary = _extract_payment_summary_block(lines)
    if summary.get("amount") is not None and summary.get("due_date"):
        result.update(summary)
    else:
        # ── Strategy 2: Simple vertical / inline fallback ──
        val = _find_inline_value(raw_text, "Total Payment Due", r"[₹Rs.\s]*[\d,]+\.\d{2}")
        if val:
            amt = parse_amount(val)
            if amt is not None:
                result["amount"] = amt

        val = _find_inline_value(raw_text, "Payment Due Date", r"\d{1,2}/\d{1,2}/\d{4}")
        if val:
            dt = parse_date(val)
            if dt:
                result["due_date"] = dt

        val = _find_inline_value(raw_text, "Statement Generation Date", r"\d{1,2}/\d{1,2}/\d{4}")
        if val:
            dt = parse_date(val)
            if dt:
                result["statement_date"] = dt

        if "bill_cycle" not in result:
            m = re.search(
                r"(\d{1,2}/\d{1,2}/\d{4})\s*[-–to]+\s*(\d{1,2}/\d{1,2}/\d{4})",
                raw_text,
            )
            if m:
                result["bill_cycle"] = f"{m.group(1)} to {m.group(2)}"

    # ── Card Mask ────────────────────────────
    m = re.search(r"\b\d{6}[Xx*•]+\d{4}\b", raw_text)
    if m:
        result["card_mask"] = m.group(0)
    else:
        masks = extract_card_masks(raw_text)
        if masks:
            result["card_mask"] = masks[0]

    # ── Card Name ────────────────────────────
    m = re.search(r"Axis Bank\s+([A-Za-z]+)\s+Credit Card", raw_text, re.IGNORECASE)
    if m:
        result["card_name"] = f"Axis Bank {m.group(1)} Credit Card"
    else:
        for line in lines:
            if "axis bank" in line.lower() and "credit card" in line.lower():
                result["card_name"] = line.strip()
                break

    # Validate
    if result.get("due_date") and result.get("amount") is not None:
        return result
    return None
