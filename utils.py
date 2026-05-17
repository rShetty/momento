"""Utility helpers: date / amount / text cleaning."""

import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation


def clean_text(raw: str) -> str:
    """Normalise whitespace and strip noise."""
    text = raw.replace("\r", " \n")
    text = re.sub(r"[^\S\n]+", " ", text)  # collapse multiple spaces except newlines
    text = re.sub(r"\n+", "\n", text)      # collapse blank lines
    return text.strip()


# ── Date parsing ────────────────────────────────

DATE_PATTERNS = [
    # 17 May 2026
    (r"(\d{1,2})[-/\s.]?([A-Za-z]{3,9})[-/\s.]?(\d{4})\b", "dmy_word"),
    # 17-05-2026   17/05/2026
    (r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b", "dmy"),
    # 2026-05-17   2026/05/17
    (r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b", "ymd"),
    # 17-05-26     (ambiguous year; prefer 2000+)
    (r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{2})\b", "dmy_short"),
]

_MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def parse_date(candidate: str) -> datetime | None:
    """Try to parse a single date string."""
    candidate = candidate.strip().lower().replace(",", "")

    # direct word month: 17 May 2026 (comma already stripped above)
    m = re.match(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})", candidate)
    if m:
        d, mon, y = m.groups()
        mon_num = _MONTH_MAP.get(mon[:3])
        if mon_num:
            try:
                return datetime(int(y), mon_num, int(d))
            except ValueError:
                pass

    # numeric separators
    for pattern, fmt in DATE_PATTERNS:
        m = re.search(pattern, candidate)
        if not m:
            continue
        a, b, c = m.groups()
        try:
            if fmt == "dmy":
                day, month, year = int(a), int(b), int(c)
                if year < 2000:
                    continue
                return datetime(year, month, day)
            elif fmt == "ymd":
                year, month, day = int(a), int(b), int(c)
                return datetime(year, month, day)
            elif fmt == "dmy_short":
                day, month, year = int(a), int(b), int(c)
                year += 2000
                return datetime(year, month, day)
        except ValueError:
            continue
    return None


def extract_dates(text: str) -> list[datetime]:
    """Extract all plausible dates from text."""
    found: list[datetime] = []
    for pattern, _ in DATE_PATTERNS:
        for m in re.finditer(pattern, text):
            dt = parse_date(m.group(0))
            if dt:
                found.append(dt)
    return found


# ── Amount parsing ──────────────────────────────

AMOUNT_RE = re.compile(
    r"(?:₹|Rs\.?|INR|Rs\.?\s*)\s*[,\d]+\.\d{2}"
    r"|"
    r"[,\d]{1,3}(?:,[,\d]{2})+\.\d{2}"
    r"|"
    r"[,\d]+\.\d{2}"
)


def parse_amount(candidate: str) -> Decimal | None:
    """Normalise an amount string and return Decimal."""
    if not candidate:
        return None
    s = candidate.replace("\u20b9", "").replace("INR", "")
    s = s.replace("Rs.", "").replace("Rs", "")
    # Handle HDFC-style currency where ₹ renders as "C" in PDF text
    s = re.sub(r"^[A-Z]", "", s.strip())
    s = s.replace(",", "").strip()
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def extract_amounts(text: str) -> list[Decimal]:
    """Extract all plausible amounts from text."""
    found: list[Decimal] = []
    text = text.replace("\u20b9", "Rs")  # normalise symbol
    for m in AMOUNT_RE.finditer(text):
        amt = parse_amount(m.group(0))
        if amt and amt > 0:
            found.append(amt)
    return found


# ── Card mask ───────────────────────────────────

# HDFC shows: 526873XXXXXX3464  (first 6 + masked middle + last 4)
# Standard:   XXXX-XXXX-XXXX-1234
CARD_MASK_RE = re.compile(
    r"\b\d{4,6}[Xx*•]+\d{4}\b"  # 526873XXXXXX3464 style
    r"|"
    r"(?:[x*•]{4}[\s-]*){3}\d{4}"  # XXXX-XXXX-XXXX-1234
    r"|"
    r"[x*•]{2,}[\s-]*\d{4}",      # XXXX-1234 fallback
    re.IGNORECASE,
)


def extract_card_masks(text: str) -> list[str]:
    return [m.group(0).strip() for m in CARD_MASK_RE.finditer(text)]


# ── Statement cycle ─────────────────────────────

# Match: 18 Mar, 2026 - 17 Apr, 2026  OR  18-Mar-2026 to 17-Apr-2026
CYCLE_RE = re.compile(
    r"(?:statement period|bill cycle|billing period)[\s:]*"
    r"(\d{1,2}\s*[A-Za-z]{3},?\s*\d{4})\s*[-–to]+\s*(\d{1,2}\s*[A-Za-z]{3},?\s*\d{4})"
    r"|"
    r"(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\s*[-–to]+\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
    re.IGNORECASE,
)


def extract_bill_cycle(text: str) -> str | None:
    m = CYCLE_RE.search(text)
    if m:
        # Determine which capture groups matched
        if m.group(1) and m.group(2):
            return f"{m.group(1)} to {m.group(2)}"
        if m.group(3) and m.group(4):
            return f"{m.group(3)} to {m.group(4)}"
    return None


# ── Table-layout helper ─────────────────────────

TABLE_KEYWORDS = [
    "total amount due",
    "minimum due",
    "due date",
    "statement date",
    "billing period",
    "credit card no",
]


def extract_next_line_value(text: str, keyword: str, cleanup: bool = True) -> str | None:
    """
    For table-layout PDFs where the value is on the line immediately AFTER the keyword.
    e.g.
        TOTAL AMOUNT DUE
        C7,168.00
    Returns the next line stripped, or None.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if keyword.lower() in line.lower():
            if i + 1 < len(lines):
                val = lines[i + 1].strip()
                if cleanup:
                    # Skip if next line is just another label
                    if any(kw.lower() in val.lower() for kw in TABLE_KEYWORDS if kw != keyword.lower()):
                        continue
                return val
    return None


DUE_DATE_KEYWORDS = [
    "payment due date",
    "due date",
    "payment due by",
    "pay by",
    "last date for payment",
]

STATEMENT_DATE_KEYWORDS = [
    "statement date",
    "statement generated on",
    "date of statement",
]

AMOUNT_KEYWORDS = [
    "total amount due",
    "amount due",
    "payment due",
    "total outstanding",
    "total due",
    "current outstanding",
]

CARD_NAME_KEYWORDS = [
    "card name",
    "card type",
    "credit card",
]


def lines_around(text: str, keyword: str, window: int = 3) -> list[str]:
    """Return `window` lines before and after the first occurrence of keyword."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if keyword.lower() in line.lower():
            start = max(0, i - window)
            end = min(len(lines), i + window + 1)
            return lines[start:end]
    return []
