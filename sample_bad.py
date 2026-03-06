# sample_bad.py — intentionally broken for testing
# This file contains known security and logic issues for testing CodeRev

import os
import sqlite3


def get_user(username):
    """Get user from database - VULNERABLE TO SQL INJECTION."""
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    # SQL injection vulnerability - user input directly in query
    query = f"SELECT * FROM users WHERE username = '{username}'"
    cursor.execute(query)
    return cursor.fetchone()


def read_file(filename):
    """Read a file - VULNERABLE TO PATH TRAVERSAL."""
    # Path traversal vulnerability - no validation of filename
    with open("/var/data/" + filename) as f:
        return f.read()


# Hardcoded secret - should be in environment variables
SECRET_KEY = "hardcoded_secret_abc123"
API_TOKEN = "sk-live-1234567890abcdef"


def process_items(items):
    """Process items - HAS OFF-BY-ONE ERROR."""
    result = []
    # Off-by-one error: range should be len(items), not len(items) + 1
    for i in range(len(items) + 1):
        result.append(items[i] * 2)
    return result


def unsafe_eval(user_code):
    """Execute user code - COMMAND INJECTION VULNERABILITY."""
    # Arbitrary code execution vulnerability
    return eval(user_code)


def get_admin_password():
    """Return admin password - INSECURE PASSWORD STORAGE."""
    # Hardcoded admin password
    return "admin123"


class UserSession:
    """User session manager with issues."""
    
    def __init__(self):
        self.sessions = {}
    
    def create_session(self, user_id):
        """Create a session - WEAK SESSION TOKEN."""
        # Predictable session token (should use secrets.token_urlsafe)
        import time
        token = str(user_id) + str(int(time.time()))
        self.sessions[token] = user_id
        return token
    
    def validate_token(self, token):
        """Validate token - NO TIMING ATTACK PROTECTION."""
        # Vulnerable to timing attacks
        return token in self.sessions


def divide(a, b):
    """Divide two numbers - MISSING ERROR HANDLING."""
    # No handling for division by zero
    return a / b


def log_sensitive_data(user_data):
    """Log user data - LOGS SENSITIVE INFORMATION."""
    # Logging potentially sensitive user data
    print(f"User data: {user_data}")
