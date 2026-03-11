"""Config loader for .coderev.toml.

Priority order (highest wins):
  1. CLI flags passed directly to pipeline / commands
  2. .coderev.toml in current working directory
  3. ~/.coderev/config.toml (user-level)
  4. Built-in defaults

Usage:
    from coderev.config import load_config
    config = load_config()           # loads from cwd and user home
    config = load_config("/path")    # loads from specific directory
"""

import sys
from pathlib import Path
from typing import Optional, Union

from .schema import CodeRevConfig

# Python 3.11+ has tomllib in stdlib; older versions need tomli
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            tomllib = None  # type: ignore[assignment]


CONFIG_FILENAME = ".coderev.toml"
USER_CONFIG_DIR = Path.home() / ".coderev"
USER_CONFIG_FILE = USER_CONFIG_DIR / "config.toml"


def load_config(
    project_dir: Optional[Union[str, Path]] = None,
    config_file: Optional[Union[str, Path]] = None,
) -> CodeRevConfig:
    """
    Load CodeRev config with priority merging.

    Args:
        project_dir: directory to search for .coderev.toml
                     (defaults to current working directory)
        config_file: explicit path to a config file (overrides search)

    Returns:
        CodeRevConfig with merged values from all sources
    """
    if tomllib is None:
        return CodeRevConfig.default()

    # Start with empty dict — Pydantic defaults fill in the rest
    merged: dict = {}

    # Layer 1: user-level config (~/.coderev/config.toml)
    if USER_CONFIG_FILE.exists():
        try:
            user_data = _load_toml(USER_CONFIG_FILE)
            merged = _deep_merge(merged, user_data)
        except Exception:
            pass  # corrupt user config is silently ignored

    # Layer 2: project-level config (.coderev.toml in project root)
    if config_file:
        project_config = Path(config_file)
    else:
        search_dir = Path(project_dir) if project_dir else Path.cwd()
        project_config = _find_config(search_dir)

    if project_config and project_config.exists():
        try:
            project_data = _load_toml(project_config)
            merged = _deep_merge(merged, project_data)
        except Exception as e:
            raise ValueError(
                f"Invalid .coderev.toml at {project_config}: {e}"
            )

    if not merged:
        return CodeRevConfig.default()

    return CodeRevConfig.model_validate(merged)


def find_project_config(start_dir: Optional[Path] = None) -> Optional[Path]:
    """Search upward from start_dir for .coderev.toml (like git does)."""
    return _find_config(start_dir or Path.cwd())


def write_default_config(path: Path) -> None:
    """Write a commented example .coderev.toml to path."""
    path.write_text(_DEFAULT_CONFIG_CONTENT, encoding="utf-8")


def _find_config(start_dir: Path) -> Optional[Path]:
    """Walk up directory tree looking for .coderev.toml."""
    current = start_dir.resolve()
    for _ in range(10):  # max 10 levels up
        candidate = current / CONFIG_FILENAME
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:  # filesystem root
            break
        current = parent
    return None


def _load_toml(path: Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Override wins on conflicts."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# ── Default Config File Content ───────────────────────────────────────────────

_DEFAULT_CONFIG_CONTENT = """\
# .coderev.toml — CodeRev configuration
# All settings are optional. Uncomment and modify as needed.
# CLI flags always override these settings.

[review]
# Fail CI when findings at or above this severity are found
# Options: critical | high | medium | low | none (default: none)
# fail_on = "high"

# Minimum confidence score to include a finding (0.0-1.0)
# min_confidence = 0.7

# Default output format: rich | json | markdown | sarif
# format = "rich"

# Model to use (must be available on Groq)
# model = "moonshotai/kimi-k2-instruct"

# Maximum diff size in lines before switching to summary mode
# max_diff_lines = 5000

[agents]
# Which review agents to run (synthesizer always runs)
# enabled = ["security", "performance", "correctness"]

[exclude]
# File path patterns to skip (glob syntax)
# paths = ["tests/**", "migrations/**", "*.min.js", "vendor/**"]

# Skip entire categories
# categories = ["style"]

[eval]
# Recall threshold for eval regression CI (0.0-1.0)
# recall_threshold = 0.80

# Precision threshold for eval regression CI (0.0-1.0)
# precision_threshold = 0.70
"""
