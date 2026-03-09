# tests/golden/performance/n_plus_one.py
# GOLDEN SAMPLE: N+1 query pattern
# Expected: 1 HIGH performance finding

import sqlite3


def get_all_users_with_orders(conn: sqlite3.Connection) -> list:
    """VULNERABLE: executes one query per user (N+1 pattern)."""
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM users")
    users = cursor.fetchall()

    results = []
    for user_id, name in users:
        # N+1: one DB query per user
        cursor.execute("SELECT * FROM orders WHERE user_id = ?", (user_id,))
        orders = cursor.fetchall()
        results.append({"user": name, "orders": orders})

    return results


def get_users_with_profiles(conn: sqlite3.Connection) -> list:
    """SAFE: uses JOIN — single query."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.id, u.name, p.bio
        FROM users u
        LEFT JOIN profiles p ON p.user_id = u.id
    """)
    return cursor.fetchall()
