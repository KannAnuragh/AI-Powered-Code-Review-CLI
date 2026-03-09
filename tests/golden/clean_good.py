# tests/golden/clean_good.py
# This file is intentionally well-written.
# A good code review tool should find ZERO critical/high findings here.

import os
import sqlite3
import secrets
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@contextmanager
def get_db_connection():
    """Context manager ensures connection always closed."""
    conn = sqlite3.connect(os.environ["DATABASE_URL"])
    try:
        yield conn
    finally:
        conn.close()


def get_user(username: str) -> dict | None:
    """Fetch user by username using parameterized query."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, email FROM users WHERE username = ?",
            (username,)
        )
        row = cursor.fetchone()
        return {"id": row[0], "username": row[1], "email": row[2]} if row else None


def generate_session_token() -> str:
    """Cryptographically secure session token."""
    return secrets.token_urlsafe(32)


def divide(a: float, b: float) -> float:
    """Safe division with explicit zero check."""
    if b == 0:
        raise ValueError("Divisor cannot be zero")
    return a / b


def process_items(items: list) -> list:
    """Correct iteration — no off-by-one."""
    return [item * 2 for item in items]
