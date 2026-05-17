"""SQLite persistence layer."""

import json
import re
import sqlite3
from datetime import datetime
from typing import Any
from pathlib import Path

from config import DB_PATH


def _now() -> str:
    return datetime.utcnow().isoformat()


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS bills (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                bank_key    TEXT    NOT NULL,
                card_name   TEXT,
                card_mask   TEXT,
                statement_date TEXT,
                due_date    TEXT,
                amount      REAL,
                bill_cycle  TEXT,
                pdf_path    TEXT,
                status      TEXT    DEFAULT 'pending',
                created_at  TEXT    DEFAULT (datetime('now')),
                paid_at     TEXT,
                UNIQUE(bank_key, statement_date, card_mask)
            );

            CREATE TABLE IF NOT EXISTS patterns (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                bank_key      TEXT    NOT NULL,
                field         TEXT    NOT NULL,
                pattern_type  TEXT    NOT NULL,   -- 'regex' | 'keyword'
                pattern_value TEXT    NOT NULL,
                confidence    REAL    DEFAULT 0.5,
                success_count INTEGER DEFAULT 0,
                fail_count    INTEGER DEFAULT 0,
                last_success  TEXT,
                created_at    TEXT    DEFAULT (datetime('now')),
                UNIQUE(bank_key, field, pattern_value)
            );

            CREATE TABLE IF NOT EXISTS reminder_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                bill_id    INTEGER NOT NULL,
                sent_at    TEXT    DEFAULT (datetime('now')),
                message    TEXT
            );

            CREATE TABLE IF NOT EXISTS failed_parses (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                bank_key   TEXT    NOT NULL,
                raw_text   TEXT,
                pdf_path   TEXT,
                llm_guess  TEXT,    -- JSON blob
                created_at TEXT    DEFAULT (datetime('now')),
                resolved   INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS registered_cards (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_chat_id    TEXT    NOT NULL,
                bank_key        TEXT    NOT NULL,
                cardholder_name TEXT    NOT NULL,
                last_4_digits   TEXT    NOT NULL,
                card_nickname   TEXT,               -- user-friendly name e.g. "My HDFC Regalia"
                password_hint   TEXT,               -- e.g. "RAJE{last4}" or "first4+last4"
                created_at      TEXT    DEFAULT (datetime('now')),
                UNIQUE(bank_key, last_4_digits, user_chat_id)
            );
            """
        )


# ── Bills ────────────────────────────────────────

def save_bill(bill: dict[str, Any]) -> int:
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO bills (bank_key, card_name, card_mask, statement_date,
                               due_date, amount, bill_cycle, pdf_path, status)
            VALUES (:bank_key, :card_name, :card_mask, :statement_date,
                    :due_date, :amount, :bill_cycle, :pdf_path, :status)
            ON CONFLICT(bank_key, statement_date, card_mask) DO UPDATE SET
                amount = excluded.amount,
                due_date = excluded.due_date,
                card_name = excluded.card_name,
                card_mask = excluded.card_mask,
                bill_cycle = excluded.bill_cycle,
                pdf_path   = excluded.pdf_path
            """,
            bill,
        )
        return cur.lastrowid


def get_bill(bill_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
        return dict(row) if row else None


def get_pending_bills() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM bills WHERE status = 'pending' ORDER BY due_date ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_pending_by_bank(bank_key: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT * FROM bills
            WHERE bank_key = ? AND status = 'pending'
            ORDER BY created_at DESC LIMIT 1
            """,
            (bank_key,),
        ).fetchone()
        return dict(row) if row else None


def mark_bill_paid(bill_id: int) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE bills SET status = 'paid', paid_at = ? WHERE id = ?",
            (_now(), bill_id),
        )


def get_pending_by_bank_month(bank_key: str, month: str) -> dict | None:
    """Find pending bill for bank where due_date is in given month (MM or YYYY-MM)."""
    # Normalize month to YYYY-MM
    if len(month) == 2:
        month = f"2026-{month}"  # assume current year; can be made smarter
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT * FROM bills
            WHERE bank_key = ? AND status = 'pending'
              AND strftime('%Y-%m', due_date) = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (bank_key, month),
        ).fetchone()
        return dict(row) if row else None


def bill_exists(bank_key: str, statement_date: str | None, card_mask: str | None) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM bills WHERE bank_key = ? AND statement_date = ? AND card_mask = ?",
            (bank_key, statement_date, card_mask),
        ).fetchone()
        return row is not None


# ── Patterns ───────────────────────────────────

def get_patterns(bank_key: str, field: str | None = None) -> list[dict]:
    with get_db() as conn:
        sql = "SELECT * FROM patterns WHERE bank_key = ?"
        params: list[Any] = [bank_key]
        if field:
            sql += " AND field = ?"
            params.append(field)
        sql += " ORDER BY confidence DESC, success_count DESC"
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def save_pattern(
    bank_key: str,
    field: str,
    pattern_type: str,
    pattern_value: str,
    confidence: float = 0.5,
) -> None:
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO patterns (bank_key, field, pattern_type, pattern_value, confidence)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(bank_key, field, pattern_value) DO UPDATE SET
                confidence = excluded.confidence,
                last_success = excluded.last_success
            """,
            (bank_key, field, pattern_type, pattern_value, confidence),
        )


def bump_pattern(pattern_id: int, success: bool) -> None:
    with get_db() as conn:
        if success:
            conn.execute(
                """
                UPDATE patterns
                SET success_count = success_count + 1,
                    confidence = MIN(1.0, confidence + 0.05),
                    last_success = ?
                WHERE id = ?
                """,
                (_now(), pattern_id),
            )
        else:
            conn.execute(
                """
                UPDATE patterns
                SET fail_count = fail_count + 1,
                    confidence = MAX(0.0, confidence - 0.1)
                WHERE id = ?
                """,
                (pattern_id,),
            )


# ── Reminders ────────────────────────────────────

def was_reminded_today(bill_id: int) -> bool:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM reminder_log
            WHERE bill_id = ? AND date(sent_at) = date('now')
            """,
            (bill_id,),
        ).fetchone()
        return row is not None


def log_reminder(bill_id: int, message: str) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO reminder_log (bill_id, message) VALUES (?, ?)",
            (bill_id, message),
        )


# ── Failed parses ────────────────────────────────

def save_failed_parse(
    bank_key: str, raw_text: str, pdf_path: str, llm_guess: dict | None
) -> int:
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO failed_parses (bank_key, raw_text, pdf_path, llm_guess)
            VALUES (?, ?, ?, ?)
            """,
            (bank_key, raw_text, pdf_path, json.dumps(llm_guess) if llm_guess else None),
        )
        return cur.lastrowid


def get_latest_failed_parse(bank_key: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT * FROM failed_parses
            WHERE bank_key = ? AND resolved = 0
            ORDER BY created_at DESC LIMIT 1
            """,
            (bank_key,),
        ).fetchone()
        return dict(row) if row else None


def resolve_failed_parse(fp_id: int) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE failed_parses SET resolved = 1 WHERE id = ?",
            (fp_id,),
        )


# ── History ─────────────────────────────────────

def get_bill_history(bank_key: str, limit: int = 10) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM bills WHERE bank_key = ? ORDER BY created_at DESC LIMIT ?",
            (bank_key, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Registered Cards ────────────────────────────

def register_card(
    user_chat_id: str,
    bank_key: str,
    cardholder_name: str,
    last_4_digits: str,
    card_nickname: str | None = None,
    password_hint: str | None = None,
) -> int:
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO registered_cards (user_chat_id, bank_key, cardholder_name,
                                          last_4_digits, card_nickname, password_hint)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(bank_key, last_4_digits, user_chat_id) DO UPDATE SET
                cardholder_name = excluded.cardholder_name,
                card_nickname   = excluded.card_nickname,
                password_hint   = excluded.password_hint
            """,
            (user_chat_id, bank_key, cardholder_name, last_4_digits, card_nickname, password_hint),
        )
        return cur.lastrowid


def get_registered_cards(user_chat_id: str | None = None) -> list[dict]:
    with get_db() as conn:
        if user_chat_id:
            rows = conn.execute(
                "SELECT * FROM registered_cards WHERE user_chat_id = ? ORDER BY created_at DESC",
                (user_chat_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM registered_cards ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def get_registered_card_by_mask(bank_key: str, card_mask: str) -> dict | None:
    """Match a registered card by bank + last-4 digits extracted from mask."""
    # card_mask might be "526873XXXXXX3464" or "XXXX-XXXX-XXXX-1234"
    last4_match = re.search(r"(\d{4})$", card_mask.replace("-", ""))
    if not last4_match:
        return None
    last4 = last4_match.group(1)
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT * FROM registered_cards
            WHERE bank_key = ? AND last_4_digits = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (bank_key, last4),
        ).fetchone()
        return dict(row) if row else None


def delete_registered_card(card_id: int) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM registered_cards WHERE id = ?", (card_id,))
