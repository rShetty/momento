"""HDFC Bank credit card statement specific extractor.

Learns from the specific table-layout used by HDFC statements where:
  - Labels and values are stacked vertically (not inline)
  - Currency symbol ₹ renders as "C" in PyMuPDF text
  - Dates use "DD MMM, YYYY" format
  - Card numbers show first 6 + masked + last 4 digits
"""

import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from utils import parse_date, parse_amount, extract_card_masks, extract_bill_cycle


def parse_hdfc_statement(raw_text: str) -> dict[str, Any] | None:
    """
    Extract all fields from an HDFC credit card statement.
    Returns a dict with at least due_date and amount on success.
    """
    lines = raw_text.splitlines()
    result: dict[str, Any] = {"bank_key": "hdfc"}

    # ── 1. Amount ───────────────────────────────
    # Layout: "TOTAL AMOUNT DUE" then "C7,168.00" on next line
    for i, line in enumerate(lines):
        if "TOTAL AMOUNT DUE" in line.upper():
            if i + 1 < len(lines):
                val = lines[i + 1].strip()
                # HDFC renders ₹ as "C" at start of amount lines
                val = val.lstrip("C")
                amt = parse_amount(val)
                if amt:
                    result["amount"] = amt
                    break

    # ── 2. Due Date ─────────────────────────────
    # Layout: "DUE DATE" then "07 May, 2026" on next line
    for i, line in enumerate(lines):
        if line.strip().upper() == "DUE DATE":
            if i + 1 < len(lines):
                val = lines[i + 1].strip()
                dt = parse_date(val)
                if dt:
                    result["due_date"] = dt
                    break

    # ── 3. Statement metadata block ─────────────
    # HDFC puts these in a 2-column vertical table:
    #   Credit Card No.
    #   Alternate Account Number
    #   Statement Date
    #   Billing Period
    #   526873XXXXXX3464
    #   0001010610002253468
    #   17 Apr, 2026
    #   18 Mar, 2026 - 17 Apr, 2026
    # We scan the block after seeing "Credit Card No."
    for i, line in enumerate(lines):
        if "Credit Card No" in line:
            block = lines[i : min(i + 10, len(lines))]
            for bl in block:
                # Statement date
                if not result.get("statement_date"):
                    dt = parse_date(bl)
                    if dt:
                        result["statement_date"] = dt

                # Bill cycle
                if not result.get("bill_cycle"):
                    cyc = extract_bill_cycle(bl)
                    if cyc:
                        result["bill_cycle"] = cyc
                    else:
                        # HDFC format: "18 Mar, 2026 - 17 Apr, 2026" without keyword prefix
                        m = re.search(
                            r"(\d{1,2}\s+[A-Za-z]{3},?\s*\d{4})\s*[-–to]+\s*(\d{1,2}\s+[A-Za-z]{3},?\s*\d{4})",
                            bl,
                        )
                        if m:
                            result["bill_cycle"] = f"{m.group(1)} to {m.group(2)}"

                # Card mask (with visible prefix like 526873XXXXXX3464)
                if not result.get("card_mask"):
                    masks = extract_card_masks(bl)
                    if masks:
                        result["card_mask"] = masks[0]

                # Also try full card number pattern
                if not result.get("card_mask"):
                    m = re.search(r"\b(\d{6}[Xx*•]+\d{4})\b", bl)
                    if m:
                        result["card_mask"] = m.group(1)
            break

    # ── 4. Card Name ────────────────────────────
    # Usually on a line like: "Swiggy HDFC Bank Credit Card Statement"
    for line in lines:
        if "HDFC Bank Credit Card Statement" in line:
            result["card_name"] = line.strip()
            break

    # Validate minimum required fields
    if result.get("due_date") and result.get("amount"):
        return result
    return None
