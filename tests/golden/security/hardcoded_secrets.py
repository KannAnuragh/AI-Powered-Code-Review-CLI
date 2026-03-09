# tests/golden/security/hardcoded_secrets.py
# GOLDEN SAMPLE: Hardcoded credentials
# Expected: 3 HIGH/CRITICAL security findings with CWE-798

import hashlib

# VULNERABLE: API key in source code
AWS_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
AWS_SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"

DATABASE_URL = "postgresql://admin:hunter2@prod-db.internal:5432/myapp"

def verify_admin(password: str) -> bool:
    """VULNERABLE: hardcoded admin password."""
    return password == "super_secret_admin_password_123"

def hash_password(password: str) -> str:
    """VULNERABLE: MD5 for password hashing (weak crypto)."""
    return hashlib.md5(password.encode()).hexdigest()
