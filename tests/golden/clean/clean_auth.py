# tests/golden/clean/clean_auth.py
# GOLDEN SAMPLE: Well-written authentication code
# Expected: ZERO critical or high findings (false positive test)

import os
import secrets
import hashlib
import hmac
from contextlib import contextmanager
import sqlite3


@contextmanager
def get_db():
    """Context manager — connection always closed."""
    conn = sqlite3.connect(os.environ["DATABASE_URL"])
    try:
        yield conn
    finally:
        conn.close()


def get_user(username: str) -> dict | None:
    """Parameterized query — no injection possible."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?",
            (username,)
        )
        row = cursor.fetchone()
        return {"id": row[0], "username": row[1], "hash": row[2]} if row else None


def verify_password(password: str, stored_hash: str) -> bool:
    """Constant-time comparison — no timing attack."""
    computed = hashlib.sha256(password.encode()).hexdigest()
    return hmac.compare_digest(computed, stored_hash)


def generate_session_token() -> str:
    """Cryptographically secure token."""
    return secrets.token_urlsafe(32)


def create_user(username: str, password: str) -> bool:
    """Parameterized insert with proper error handling."""
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, password_hash)
            )
            conn.commit()
            return True
    except sqlite3.IntegrityError:
        return False
