"""Utility functions for CodeRev.

Helpers for file reading, diff parsing, language detection, and cost estimation.
"""

import re
import sys
from pathlib import Path
from typing import Optional


# Language extension mapping
LANGUAGE_MAPPING: dict[str, str] = {
    ".py": "Python",
    ".pyi": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript (React)",
    ".js": "JavaScript",
    ".jsx": "JavaScript (React)",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".c": "C",
    ".h": "C/C++",
    ".swift": "Swift",
    ".scala": "Scala",
    ".clj": "Clojure",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".erl": "Erlang",
    ".hs": "Haskell",
    ".lua": "Lua",
    ".r": "R",
    ".R": "R",
    ".jl": "Julia",
    ".sh": "Shell",
    ".bash": "Bash",
    ".zsh": "Zsh",
    ".ps1": "PowerShell",
    ".sql": "SQL",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sass": "Sass",
    ".less": "Less",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".xml": "XML",
    ".toml": "TOML",
    ".md": "Markdown",
    ".rst": "reStructuredText",
    ".tf": "Terraform",
    ".dockerfile": "Dockerfile",
}

# Token pricing per model (input_rate, output_rate) in USD per token
# Last updated: 2026-03-06
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "kimi-k2-0528": (0.0000014, 0.0000014),           # $1.40/M tokens in+out
    "moonshotai/kimi-k2": (0.0000014, 0.0000014),     # alias
    "llama-4-scout": (0.0000001, 0.0000001),           # fallback model
    "qwen-3-32b": (0.0000009, 0.0000009),              # fallback model
}


def detect_language(file_path: str) -> str:
    """Map file extension to language name for prompt context.
    
    Args:
        file_path: Path to the file (can be relative or absolute)
        
    Returns:
        Human-readable language name, or 'Unknown' if not recognized
    """
    path = Path(file_path)
    
    # Handle special files without extensions
    filename_lower = path.name.lower()
    if filename_lower == "dockerfile":
        return "Dockerfile"
    if filename_lower == "makefile":
        return "Makefile"
    if filename_lower in ("jenkinsfile",):
        return "Groovy"
    
    ext = path.suffix.lower()
    return LANGUAGE_MAPPING.get(ext, "Unknown")


def extract_files_from_diff(diff: str) -> list[str]:
    """Parse diff headers to extract changed file paths.
    
    Handles both git diff format:
        diff --git a/path/to/file b/path/to/file
        
    And unified diff format:
        --- a/path/to/file
        +++ b/path/to/file
    
    Args:
        diff: The full diff content as a string
        
    Returns:
        List of unique file paths found in the diff
    """
    files: set[str] = set()
    
    # Git diff format: diff --git a/path b/path
    git_diff_pattern = r'^diff --git a/.+ b/(.+)$'
    files.update(re.findall(git_diff_pattern, diff, re.MULTILINE))
    
    # Unified diff format: +++ b/path
    unified_pattern = r'^\+\+\+ b/(.+)$'
    files.update(re.findall(unified_pattern, diff, re.MULTILINE))
    
    # Also try without the b/ prefix for some diff formats
    unified_no_prefix = r'^\+\+\+ (.+)$'
    for match in re.findall(unified_no_prefix, diff, re.MULTILINE):
        # Skip /dev/null (deleted files)
        if match != "/dev/null" and not match.startswith("b/"):
            files.add(match)
    
    return sorted(files)


def detect_languages_in_diff(diff: str) -> list[str]:
    """Detect all unique languages present in a diff.
    
    Args:
        diff: The full diff content
        
    Returns:
        Sorted list of unique language names
    """
    files = extract_files_from_diff(diff)
    languages = {detect_language(f) for f in files}
    languages.discard("Unknown")
    return sorted(languages)


def estimate_cost(input_tokens: int, output_tokens: int, model: str) -> float:
    """Estimate API cost in USD based on token usage.
    
    Args:
        input_tokens: Number of input tokens used
        output_tokens: Number of output tokens generated
        model: Model identifier string
        
    Returns:
        Estimated cost in USD, rounded to 4 decimal places
    """
    # Default to Kimi K2 pricing if model not found
    input_rate, output_rate = MODEL_PRICING.get(model, (0.0000014, 0.0000014))
    cost = (input_tokens * input_rate) + (output_tokens * output_rate)
    return round(cost, 4)


def format_cost(cost: float) -> str:
    """Format cost as a human-readable string.
    
    Args:
        cost: Cost in USD
        
    Returns:
        Formatted string like '$0.023' or '<$0.01'
    """
    if cost < 0.001:
        return "<$0.001"
    if cost < 0.01:
        return f"~${cost:.3f}"
    return f"~${cost:.2f}"


def read_diff_from_file(path: Path) -> str:
    """Read diff content from a file.
    
    Args:
        path: Path to the diff/patch file
        
    Returns:
        Diff content as a string
        
    Raises:
        FileNotFoundError: If the file doesn't exist
        PermissionError: If the file can't be read
    """
    return path.read_text(encoding="utf-8")


def read_diff_from_stdin() -> Optional[str]:
    """Read diff content from stdin if available.
    
    Returns:
        Diff content if stdin has data, None otherwise
    """
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return None


def read_files_list(path: Path) -> list[str]:
    """Read a list of file paths from a file (one per line).
    
    Args:
        path: Path to the file containing the list
        
    Returns:
        List of file paths, with empty lines and comments removed
    """
    content = path.read_text(encoding="utf-8")
    lines = content.strip().split("\n")
    # Filter out empty lines and comments
    return [
        line.strip() 
        for line in lines 
        if line.strip() and not line.strip().startswith("#")
    ]


def count_diff_lines(diff: str) -> int:
    """Count the number of lines in a diff.
    
    Args:
        diff: The diff content
        
    Returns:
        Number of lines
    """
    return diff.count('\n') + (1 if diff and not diff.endswith('\n') else 0)


def get_severity_exit_code(findings: list, fail_on: str) -> int:
    """Determine exit code based on findings and fail-on threshold.
    
    Args:
        findings: List of Finding objects
        fail_on: Severity threshold ('critical', 'high', 'medium', 'low', 'info')
        
    Returns:
        Exit code: 1 if threshold exceeded, 0 otherwise
    """
    from .schema import Severity
    
    severity_order = {
        "info": 0,
        "low": 1,
        "medium": 2,
        "high": 3,
        "critical": 4,
    }
    
    fail_threshold = severity_order.get(fail_on.lower(), 4)
    
    for finding in findings:
        finding_level = severity_order.get(finding.severity.value, 0)
        if finding_level >= fail_threshold:
            return 1
    
    return 0


def truncate_diff_for_display(diff: str, max_lines: int = 50) -> str:
    """Truncate a diff for display purposes.
    
    Args:
        diff: The full diff content
        max_lines: Maximum number of lines to include
        
    Returns:
        Truncated diff with indicator if truncated
    """
    lines = diff.split('\n')
    if len(lines) <= max_lines:
        return diff
    
    truncated = '\n'.join(lines[:max_lines])
    remaining = len(lines) - max_lines
    return f"{truncated}\n... ({remaining} more lines)"
