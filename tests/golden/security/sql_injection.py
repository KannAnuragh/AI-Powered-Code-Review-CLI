# tests/golden/security/sql_injection.py
# GOLDEN SAMPLE: SQL Injection patterns
# Expected: 2 CRITICAL security findings with CWE-89

import sqlite3


def get_user_by_name(username: str):
    """VULNERABLE: f-string in SQL query."""
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    query = f"SELECT * FROM users WHERE username = '{username}'"
    cursor.execute(query)
    return cursor.fetchone()


def search_products(category: str, sort_by: str):
    """VULNERABLE: string concatenation in ORDER BY clause."""
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    sql = "SELECT * FROM products WHERE category = '" + category + "' ORDER BY " + sort_by
    cursor.execute(sql)
    return cursor.fetchall()


def get_user_by_id(user_id: int):
    """SAFE: parameterized query — should NOT be flagged."""
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    return cursor.fetchone()
