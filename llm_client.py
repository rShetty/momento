"""OpenRouter LLM client for PDF parsing fallback."""

import json
import re
from typing import Any

import requests

from config import OPENROUTER_API_KEY, OPENROUTER_MODEL


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


SYSTEM_PROMPT = (
    "You are a financial document analyst. "
    "Extract the following fields from the Indian credit card statement text provided. "
    "Use the exact keys shown. If a field is not present, use null. "
    "Amounts should be numbers without currency symbols or commas. "
    "Dates should be ISO format YYYY-MM-DD where possible, or keep original string if ambiguous. "
    "Card mask should show masked digits like XXXX-XXXX-XXXX-1234. "
    "\n\nReturn ONLY a valid JSON object with these keys:\n"
    "- bank_name\n"
    "- card_name (product name e.g. 'HDFC Regalia')\n"
    "- card_mask\n"
    "- statement_date (ISO or raw string)\n"
    "- due_date (ISO or raw string)\n"
    "- amount_due (number)\n"
    "- bill_cycle (string like '15-Apr to 14-May')\n"
)


def _trim_text(text: str, max_chars: int = 6000) -> str:
    """Send enough context without blowing the token budget."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[truncated]"


def parse_with_llm(raw_text: str) -> dict[str, Any] | None:
    """Ask OpenRouter LLM to extract structured data from statement text."""
    if not OPENROUTER_API_KEY:
        print("LLM fallback skipped: no OPENROUTER_API_KEY")
        return None

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _trim_text(raw_text)},
        ],
        "temperature": 0.1,
        "max_tokens": 512,
    }

    try:
        resp = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return _extract_json(content)
    except Exception as exc:
        print(f"LLM call failed: {exc}")
        return None


def _extract_json(text: str) -> dict[str, Any] | None:
    """Robustly extract JSON from LLM output which may wrap it in markdown."""
    text = text.strip()
    # fenced code block
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    return None


def parse_with_llm_for_amount_due(raw_text: str) -> dict[str, Any] | None:
    """Lightweight LLM call focused only on amount and due date."""
    lightweight_prompt = (
        "Extract from this Indian credit card statement:\n"
        "   total_amount_due (number only)\n"
        "   due_date (YYYY-MM-DD or raw)\n"
        "   statement_date (YYYY-MM-DD or raw)\n"
        "Return only JSON."
    )
    if not OPENROUTER_API_KEY:
        return None
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": lightweight_prompt},
            {"role": "user", "content": _trim_text(raw_text)},
        ],
        "temperature": 0.1,
        "max_tokens": 256,
    }
    try:
        resp = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return _extract_json(content)
    except Exception as exc:
        print(f"Lightweight LLM call failed: {exc}")
        return None
