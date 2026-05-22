"""Pattern matching engine: tries known patterns before falling back."""

import json
import re
from datetime import datetime
from decimal import Decimal
from typing import Any

import db
from llm_client import parse_with_llm
from utils import (
    AMOUNT_KEYWORDS,
    CARD_MASK_RE,
    DUE_DATE_KEYWORDS,
    STATEMENT_DATE_KEYWORDS,
    extract_amounts,
    extract_bill_cycle,
    extract_card_masks,
    extract_dates,
    lines_around,
    parse_amount,
    parse_date,
)

# Bank-specific extractors
_BANK_EXTRACTORS = {
    "hdfc": None,  # imported lazily below to avoid circular imports
}


FIELDS = ["due_date", "amount", "statement_date", "card_name", "card_mask", "bill_cycle"]


def parse_statement(bank_key: str, raw_text: str) -> dict[str, Any] | None:
    """
    Try to parse a statement using known patterns.
    Returns a dict on success, None if nothing worked.
    """
    # ── Bank-specific extractor (highest priority) ──
    if bank_key == "hdfc":
        from hdfc_extractor import parse_hdfc_statement
        result = parse_hdfc_statement(raw_text)
        if result:
            return result
    if bank_key == "axis":
        from axis_extractor import parse_axis_statement
        result = parse_axis_statement(raw_text)
        if result:
            return result
    if bank_key == "icici":
        from icici_extractor import parse_icici_statement
        result = parse_icici_statement(raw_text)
        if result:
            return result
    if bank_key == "sbi":
        from sbi_extractor import parse_sbi_statement
        result = parse_sbi_statement(raw_text)
        if result:
            return result
    if bank_key == "hsbc":
        from hsbc_extractor import parse_hsbc_statement
        result = parse_hsbc_statement(raw_text)
        if result:
            return result
    if bank_key == "yes":
        from yes_extractor import parse_yes_statement
        result = parse_yes_statement(raw_text)
        if result:
            return result

    # ── Generic pattern matching ────────────────────
    result: dict[str, Any] = {"bank_key": bank_key}
    all_patterns = db.get_patterns(bank_key)

    # field -> list of patterns ordered by confidence
    by_field: dict[str, list[dict]] = {f: [] for f in FIELDS}
    for p in all_patterns:
        by_field[p["field"]].append(p)

    for field in FIELDS:
        for pat in by_field.get(field, []):
            value = _apply_pattern(pat, raw_text)
            if value is not None:
                result[field] = value
                db.bump_pattern(pat["id"], success=True)
                break
            else:
                db.bump_pattern(pat["id"], success=False)

    # Accept if we at least got due_date and amount
    if "due_date" in result and "amount" in result:
        return result
    return None


def _apply_pattern(pattern: dict, raw_text: str) -> Any:
    """Apply a single pattern against raw text."""
    ptype = pattern["pattern_type"]
    value = pattern["pattern_value"]
    field = pattern["field"]

    if ptype == "regex":
        m = re.search(value, raw_text, re.IGNORECASE)
        if not m:
            return None
        try:
            group = m.group(1)
        except IndexError:
            group = m.group(0)
        return _coerce(field, group)

    if ptype == "keyword":
        # Look at lines containing the keyword, prefer same-line match
        snippet_lines = lines_around(raw_text, value, window=2)
        if not snippet_lines:
            return None

        # First pass: look on the same line as the keyword
        keyword_lower = value.lower()
        for line in snippet_lines:
            if keyword_lower in line.lower():
                if field in ("due_date", "statement_date"):
                    dates = extract_dates(line)
                    if dates:
                        return dates[0]
                if field == "amount":
                    amts = extract_amounts(line)
                    if amts:
                        return amts[0]
                if field == "card_mask":
                    masks = extract_card_masks(line)
                    if masks:
                        return masks[0]
                if field == "bill_cycle":
                    cycle = extract_bill_cycle(line)
                    if cycle:
                        return cycle

        # Second pass: scan the whole snippet window
        snippet = "\n".join(snippet_lines)
        if field in ("due_date", "statement_date"):
            dates = extract_dates(snippet)
            return dates[0] if dates else None
        if field == "amount":
            amts = extract_amounts(snippet)
            return amts[0] if amts else None
        if field == "card_mask":
            masks = extract_card_masks(snippet)
            return masks[0] if masks else None
        if field == "bill_cycle":
            return extract_bill_cycle(snippet)
        return None

    return None


def _coerce(field: str, value: str) -> Any:
    """Coerce a matched string to the expected type."""
    if field in ("due_date", "statement_date"):
        dt = parse_date(value)
        return dt
    if field == "amount":
        amt = parse_amount(value)
        return amt
    return value.strip()


def llm_fallback(bank_key: str, raw_text: str) -> dict[str, Any] | None:
    """Use LLM to extract all fields when patterns fail."""
    llm_result = parse_with_llm(raw_text)
    if not llm_result:
        return None

    out: dict[str, Any] = {"bank_key": bank_key}

    # Map LLM keys to our schema
    due_raw = llm_result.get("due_date")
    out["due_date"] = parse_date(str(due_raw)) if due_raw else None

    stmt_raw = llm_result.get("statement_date")
    out["statement_date"] = parse_date(str(stmt_raw)) if stmt_raw else None

    amt = llm_result.get("amount_due")
    if isinstance(amt, (int, float, Decimal)):
        out["amount"] = Decimal(str(amt))
    elif isinstance(amt, str):
        out["amount"] = parse_amount(amt)

    out["card_name"] = llm_result.get("card_name")
    out["card_mask"] = llm_result.get("card_mask")
    out["bill_cycle"] = llm_result.get("bill_cycle")

    if out.get("due_date") and out.get("amount"):
        return out
    return None


def heuristic_fallback(bank_key: str, raw_text: str) -> dict[str, Any] | None:
    """Last-ditch heuristic before giving up."""
    out: dict[str, Any] = {"bank_key": bank_key}

    # due date via keywords
    for kw in DUE_DATE_KEYWORDS:
        lines = lines_around(raw_text, kw, window=2)
        if lines:
            dates = extract_dates("\n".join(lines))
            if dates:
                out["due_date"] = dates[0]
                break

    # amount via keywords
    for kw in AMOUNT_KEYWORDS:
        lines = lines_around(raw_text, kw, window=2)
        if lines:
            amts = extract_amounts("\n".join(lines))
            if amts:
                out["amount"] = amts[0]
                break

    # statement date
    for kw in STATEMENT_DATE_KEYWORDS:
        lines = lines_around(raw_text, kw, window=2)
        if lines:
            dates = extract_dates("\n".join(lines))
            if dates:
                out["statement_date"] = dates[0]
                break

    out["card_mask"] = next(iter(extract_card_masks(raw_text)), None)
    out["bill_cycle"] = extract_bill_cycle(raw_text)

    if out.get("due_date") and out.get("amount"):
        return out
    return None
