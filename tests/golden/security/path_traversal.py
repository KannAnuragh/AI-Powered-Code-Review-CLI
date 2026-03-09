# tests/golden/security/path_traversal.py
# GOLDEN SAMPLE: Path traversal patterns
# Expected: 2 CRITICAL security findings with CWE-22

import os


def read_user_file(filename: str) -> str:
    """VULNERABLE: direct concatenation, no validation."""
    base_path = "/var/app/uploads/"
    full_path = base_path + filename
    with open(full_path) as f:
        return f.read()


def serve_template(template_name: str) -> str:
    """VULNERABLE: os.path.join doesn't prevent traversal with absolute path."""
    templates_dir = "/var/app/templates"
    template_path = os.path.join(templates_dir, template_name)
    with open(template_path) as f:
        return f.read()


def read_config(config_name: str) -> str:
    """SAFE: basename strips traversal sequences."""
    safe_name = os.path.basename(config_name)
    config_path = os.path.join("/var/app/config", safe_name)
    with open(config_path) as f:
        return f.read()
