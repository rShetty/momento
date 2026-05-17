"""One-shot script to learn from the real HDFC PDF and test the pipeline."""

import os
import re
from pathlib import Path
from datetime import datetime
from decimal import Decimal

os.chdir('/Users/rshetty/fun/kreditkard')

from pdf_extractor import extract_text
from db import init_db, save_pattern, get_patterns
from utils import (
    extract_dates, parse_date, parse_amount, extract_amounts,
    extract_card_masks, extract_bill_cycle, lines_around, extract_next_line_value
)
from pattern_matcher import parse_statement, heuristic_fallback
from pattern_generator import generate_patterns_from_teach

# Fresh DB
if os.path.exists('kreditkard.db'):
    os.remove('kreditkard.db')
init_db()

# Extract text from real HDFC PDF
pdf = Path('/Users/rshetty/fun/kreditkard/5268XXXXXXXXXX64_17-04-2026_880.pdf')
text = extract_text(pdf, password='YOUR_PDF_PASSWORD_HERE')  # Replace with actual password

# ── 1. Manual field extraction from real PDF ────
print("=== MANUAL FIELD EXTRACTION ===")

# Total Amount Due - table layout: value is on next line
amount_str = extract_next_line_value(text, "TOTAL AMOUNT DUE")
print(f"After 'TOTAL AMOUNT DUE': {amount_str}")
amount = parse_amount(amount_str) if amount_str else None
print(f"Parsed amount: {amount}")

# Due Date - table layout
due_str = extract_next_line_value(text, "DUE DATE")
print(f"After 'DUE DATE': {due_str}")
due_date = parse_date(due_str) if due_str else None
print(f"Parsed due_date: {due_date}")

# Statement Date - table layout (4 labels stacked, then 4 values)
stmt_str = extract_next_line_value(text, "Statement Date")
print(f"After 'Statement Date': {stmt_str}")
# In this PDF, the value for Statement Date is actually 2 lines down because
# Credit Card No. → Alternate Account No. → Statement Date → Billing Period
# 526873XXXXXX3464 → 0001010610002253468 → 17 Apr, 2026 → 18 Mar, 2026 - 17 Apr, 2026
# So extract_next_line_value gets the NEXT label, not the value.
# We need a smarter multi-label table scanner.

# Manual scan for the table block
lines = text.splitlines()
stmt_date = None
bill_cycle = None
card_mask = None
for i, line in enumerate(lines):
    if line.strip() == "Statement Date":
        # Look ahead: values should appear after all labels
        # Labels: Credit Card No. / Alternate Account Number / Statement Date / Billing Period
        # Values: 526873XXXXXX3464 / 0001010610002253468 / 17 Apr, 2026 / 18 Mar, 2026 - 17 Apr, 2026
        block = lines[i:i+8]
        print(f"Block around Statement Date: {block}")
        for bl in block:
            dt = parse_date(bl)
            if dt and not stmt_date:
                stmt_date = dt
                print(f"  Found statement date in block: {stmt_date}")
            if not bill_cycle:
                cyc = extract_bill_cycle(bl)
                if cyc:
                    bill_cycle = cyc
                    print(f"  Found bill cycle in block: {bill_cycle}")
            if not card_mask:
                masks = extract_card_masks(bl)
                if masks:
                    card_mask = masks[0]
                    print(f"  Found card mask in block: {card_mask}")
        break

# Card name from title
card_name = None
for line in lines:
    if 'Credit Card Statement' in line and 'HDFC' in line:
        card_name = line.strip()
        print(f"Card name line: {card_name}")
        break

print()
print("=== EXTRACTED VALUES ===")
print(f"  amount:       {amount}")
print(f"  due_date:     {due_date}")
print(f"  stmt_date:    {stmt_date}")
print(f"  bill_cycle:   {bill_cycle}")
print(f"  card_mask:    {card_mask}")
print(f"  card_name:    {card_name}")

# ── 2. Teach the system ──────────────────────
print()
print("=== TEACHING THE SYSTEM ===")

known = {
    'due_date': due_date.strftime('%d %b, %Y') if due_date else None,
    'amount': str(amount) if amount else None,
    'statement_date': stmt_date.strftime('%d %b, %Y') if stmt_date else None,
    'bill_cycle': bill_cycle,
    'card_mask': card_mask,
    'card_name': card_name,
}

# Only teach non-None values
known = {k: v for k, v in known.items() if v}
generate_patterns_from_teach('hdfc', text, known)

# ── 3. Verify learned patterns work ──────────
print()
print("=== VERIFYING LEARNED PATTERNS ===")
patterns = get_patterns('hdfc')
print(f"Total patterns: {len(patterns)}")
for p in patterns:
    print(f"  {p['field']:12s} {p['pattern_type']:8s} {p['pattern_value'][:60]}")

result = parse_statement('hdfc', text)
print()
print(f"Parse result: {result}")

if result and result.get('due_date') and result.get('amount'):
    print("✅ Successfully parsed with learned patterns!")
else:
    print("❌ Parse still incomplete")

    # Debug: test each pattern individually
    import db
    for p in patterns:
        from pattern_matcher import _apply_pattern
        val = _apply_pattern(p, text)
        print(f"  Pattern {p['field']}: {val}")

    # Also test heuristic
    print()
    print("=== HEURISTIC FALLBACK ===")
    h = heuristic_fallback('hdfc', text)
    print(f"Heuristic result: {h}")
