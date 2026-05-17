"""Reverse-engineer regex patterns from known correct values."""

import re
from typing import Any

import db
from utils import (
    AMOUNT_KEYWORDS,
    DUE_DATE_KEYWORDS,
    STATEMENT_DATE_KEYWORDS,
    extract_amounts,
    extract_dates,
    extract_card_masks,
    extract_bill_cycle,
    lines_around,
)


def generate_patterns_from_teach(
    bank_key: str,
    raw_text: str,
    known: dict[str, Any],
) -> None:
    """
    Given a text and user-provided correct values,
    generate + store regex / keyword patterns for all supplied fields.
    """
    for field, value in known.items():
        if not value:
            continue
        pat_type, pat_value = _infer_pattern(raw_text, field, str(value))
        if pat_value:
            confidence = 1.0  # human-verified
            db.save_pattern(bank_key, field, pat_type, pat_value, confidence)
            print(f"[pattern] Saved {pat_type} for {bank_key}/{field}: {pat_value}")


def auto_save_patterns_from_llm(bank_key: str, raw_text: str, llm_result: dict[str, Any]) -> None:
    """After LLM succeeds, generate patterns with lower confidence."""
    for field in ["due_date", "amount", "statement_date", "bill_cycle", "card_mask", "card_name"]:
        value = llm_result.get(field)
        if not value:
            continue
        pat_type, pat_value = _infer_pattern(raw_text, field, str(value))
        if pat_value:
            db.save_pattern(bank_key, field, pat_type, pat_value, confidence=0.5)


def _infer_pattern(raw_text: str, field: str, known_value: str) -> tuple[str, str]:
    """Try to build a regex / anchor from a known correct value."""
    known_norm = known_value.strip().lower()

    # 1. Try exact search in text (case-insensitive)
    lines = raw_text.splitlines()
    for i, line in enumerate(lines):
        if known_norm in line.lower():
            # First: try to build a line-specific regex (best quality)
            regex = _line_to_regex(line, known_value, field)
            if regex:
                # Verify it actually matches against the full text
                if re.search(regex, raw_text, re.IGNORECASE):
                    return "regex", regex

            # Fallback: use the label as a keyword anchor
            left = line.lower().split(known_norm)[0]
            if left.strip():
                label = _clean_label(left)
                if label:
                    return "keyword", label

            break  # only use first occurrence

    # Fallback: try known generic keywords for the field
    keyword = _keyword_for_field(field)
    if keyword:
        return "keyword", keyword

    return "keyword", known_norm[:20]


def _line_to_regex(line: str, known_value: str, field: str) -> str | None:
    """Build a regex from the exact line containing the known value."""
    line_lower = line.lower()
    val_lower = known_value.strip().lower()
    idx = line_lower.find(val_lower)
    if idx == -1:
        return None

    # Text before the value → becomes the label anchor
    before = line[:idx].strip()
    before = re.sub(r"[:\s]+$", "", before)
    if not before or len(before) < 3:
        return None

    # Build appropriate capture group based on field type
    if field in ("due_date", "statement_date"):
        capture = r"([\d\-/.]+\d{4})"
    elif field == "amount":
        capture = r"([₹Rs.\s]*[\d,]+\.\d{2})"
    elif field == "card_mask":
        capture = r"([Xx*•\d\s\-]+)"
    elif field == "bill_cycle":
        capture = r"(.+)"
    elif field == "card_name":
        capture = r"(.+)"
    else:
        capture = r"(.+)"

    regex = f"{re.escape(before)}[\\s:]*{capture}"

    # Verify: does it match the original line (anchored to avoid partial matches)?
    anchored = f"(?:^|[\\b]){regex}"
    if re.search(anchored, line, re.IGNORECASE):
        return regex
    return None


def _clean_label(left: str) -> str | None:
    """Extract clean label text before a known value."""
    cleaned = re.sub(r"[:\-\s]+$", "", left.strip())
    if len(cleaned) > 3:
        return cleaned
    return None


def _keyword_for_field(field: str) -> str | None:
    """Return a representative keyword to use as anchor."""
    if field == "due_date":
        return DUE_DATE_KEYWORDS[0] if DUE_DATE_KEYWORDS else None
    if field == "amount":
        return AMOUNT_KEYWORDS[0] if AMOUNT_KEYWORDS else None
    if field == "statement_date":
        return STATEMENT_DATE_KEYWORDS[0] if STATEMENT_DATE_KEYWORDS else None
    return None
