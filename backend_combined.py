"""Single-file backend build of CodeRev.

This file combines all backend modules into one Python file
without changing business logic. Internal package imports were
flattened so everything resolves within this module.
"""

# ===== BEGIN coderev\__init__.py =====
"""CodeRev - AI-powered code review CLI using Groq (Kimi K2)."""

__version__ = "0.5.0"


# ===== END coderev\__init__.py =====

# ===== BEGIN coderev\schema.py =====
"""Pydantic models for structured AI code review output.

This module defines the contract between the AI and the rest of the system.
All agents must conform to these schemas.
"""

from enum import Enum
from typing import Literal, Optional
import uuid

from pydantic import BaseModel, Field, computed_field, field_validator


class Severity(str, Enum):
    """Severity levels for code review findings.
    
    Calibration guide:
    - CRITICAL: Exploitable vulnerability, data loss risk, or auth bypass possible
    - HIGH: Likely bug in production, significant degradation
    - MEDIUM: Possible issue under edge cases
    - LOW: Minor improvement opportunity
    - INFO: Style or best practice note only
    """
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class Category(str, Enum):
    """Categories for classifying code review findings."""
    SECURITY = "security"
    PERFORMANCE = "performance"
    CORRECTNESS = "correctness"
    STYLE = "style"
    TEST_COVERAGE = "test_coverage"


class LineRange(BaseModel):
    """Represents a range of lines in a source file."""
    start: int = Field(..., ge=1, description="Starting line number (1-indexed)")
    end: int = Field(..., ge=1, description="Ending line number (1-indexed)")
    
    def __str__(self) -> str:
        if self.start == self.end:
            return f"L:{self.start}"
        return f"L:{self.start}–{self.end}"


class Finding(BaseModel):
    """A single code review finding.
    
    Each finding represents a specific issue found in the code diff,
    with enough context for developers to understand and fix it.
    """
    id: str = Field(
        default_factory=lambda: str(uuid.uuid4())[:8],
        description="Unique identifier for deduplication and reference"
    )
    category: Category = Field(..., description="Category of the finding")
    severity: Severity = Field(..., description="Severity level of the finding")
    file_path: str = Field(..., description="Path to the file containing the issue")
    line_range: Optional[LineRange] = Field(
        None, 
        description="Line range where the issue occurs. Omit if uncertain."
    )
    title: str = Field(
        ..., 
        min_length=5,
        description="Precise, descriptive title (e.g., 'Unsanitized user input in SQL query')"
    )
    description: str = Field(..., description="Detailed explanation of the issue")
    suggested_fix: Optional[str] = Field(
        None,
        description="Actual code snippet showing the fix, not prose"
    )
    references: list[str] = Field(
        default_factory=list,
        description="CWE IDs, OWASP links, PEP numbers, or other relevant references"
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score (0.0–1.0) reflecting certainty of the finding"
    )


class ReviewMetadata(BaseModel):
    """Metadata about the code review process."""
    model: str = Field(..., description="Claude model used for the review")
    total_tokens: int = Field(..., ge=0, description="Total tokens used (input + output)")
    processing_time_seconds: float = Field(..., ge=0, description="Time taken for the review")
    diff_lines: int = Field(..., ge=0, description="Number of lines in the diff")
    files_reviewed: int = Field(..., ge=0, description="Number of files reviewed")
    cache_hit_rate: float = 0.0
    cache_entries_used: int = 0  


class CodeReviewResult(BaseModel):
    """Complete result of a code review.
    
    This is the top-level schema that Claude must produce.
    All fields are validated with Pydantic for type safety.
    """
    metadata: ReviewMetadata = Field(
        ..., 
        description="Metadata about the review process"
    )
    summary: str = Field(
        ..., 
        description="One-line verdict summarizing the review"
    )
    overall_risk: Severity = Field(
        ..., 
        description="Overall risk level based on the most severe finding"
    )
    findings: list[Finding] = Field(
        default_factory=list,
        description="List of individual findings"
    )
    praise: list[str] = Field(
        default_factory=list,
        description="Specific things done well in the code (1–3 items)"
    )
    
    def get_findings_by_severity(self, severity: Severity) -> list[Finding]:
        """Filter findings by severity level."""
        return [f for f in self.findings if f.severity == severity]
    
    def get_findings_by_category(self, category: Category) -> list[Finding]:
        """Filter findings by category."""
        return [f for f in self.findings if f.category == category]
    
    def get_findings_above_confidence(self, threshold: float) -> list[Finding]:
        """Filter findings by minimum confidence threshold."""
        return [f for f in self.findings if f.confidence >= threshold]
    
    def has_critical_findings(self) -> bool:
        """Check if there are any critical severity findings."""
        return any(f.severity == Severity.CRITICAL for f in self.findings)
    
    def has_findings_at_severity(self, severity: Severity) -> bool:
        """Check if there are findings at or above a given severity."""
        severity_order = [Severity.INFO, Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
        min_index = severity_order.index(severity)
        return any(severity_order.index(f.severity) >= min_index for f in self.findings)
    
    def count_by_severity(self) -> dict[Severity, int]:
        """Count findings by severity level."""
        counts = {s: 0 for s in Severity}
        for finding in self.findings:
            counts[finding.severity] += 1
        return counts


# ── Eval System Models ────────────────────────────────────────────────


class ExpectedFinding(BaseModel):
    """Describes a finding that MUST be present in a review of a golden sample."""
    category: Category
    severity: Severity
    title_keywords: list[str]
    line_range_approximate: Optional[LineRange] = None
    references_must_include: list[str] = []
    severity_minimum: Optional[Severity] = None


class GoldenSample(BaseModel):
    """A curated test case with known vulnerabilities and expected findings."""
    id: str
    description: str
    file_name: str
    source_code: str
    expected_findings: list[ExpectedFinding]
    expected_categories: list[Category]
    false_positive_check: bool = False


class FindingMatch(BaseModel):
    """Result of matching one expected finding against actual pipeline output."""
    expected: ExpectedFinding
    matched: Optional[Finding] = None
    is_match: bool = False
    severity_correct: bool = False
    line_accurate: bool = False
    confidence_score: float = 0.0


class EvalResult(BaseModel):
    """Full evaluation result for one golden sample."""
    sample_id: str
    timestamp: str
    model: str
    pipeline_version: str

    recall: float
    precision: float
    severity_accuracy: float
    line_accuracy: float

    expected_count: int
    found_count: int
    actual_count: int
    false_positive_count: int

    matches: list[FindingMatch]

    tokens_used: int
    cost_usd: float
    processing_time_seconds: float


class EvalSummary(BaseModel):
    """Aggregate metrics across all golden samples in one eval run."""
    run_id: str
    timestamp: str
    model: str
    pipeline_version: str
    total_samples: int
    samples_passed: int
    samples_failed: list[str]

    avg_recall: float
    avg_precision: float
    avg_severity_accuracy: float
    avg_line_accuracy: float
    avg_tokens_per_sample: float
    avg_cost_per_sample: float
    total_cost_usd: float

    recall_threshold: float = 0.80
    precision_threshold: float = 0.70

    @computed_field
    @property
    def passed(self) -> bool:
        return (self.avg_recall >= self.recall_threshold and
                self.avg_precision >= self.precision_threshold)


# ── Config Models ─────────────────────────────────────────────────────


class ReviewConfig(BaseModel):
    """[review] section of .coderev.toml"""
    fail_on: Optional[Severity] = None
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    format: Literal["rich", "json", "markdown", "sarif"] = "rich"
    model: str = "moonshotai/kimi-k2-instruct"
    no_cache: bool = False
    max_diff_lines: int = Field(default=5000, ge=100)

    @field_validator("fail_on", mode="before")
    @classmethod
    def parse_fail_on(cls, v):
        if v is None or v == "none":
            return None
        return Severity(v)


class AgentsConfig(BaseModel):
    """[agents] section of .coderev.toml"""
    enabled: list[Literal[
        "security", "performance", "correctness"
    ]] = ["security", "performance", "correctness"]


class ExcludeConfig(BaseModel):
    """[exclude] section of .coderev.toml"""
    paths: list[str] = []
    categories: list[Category] = []
    severities: list[Severity] = []


class EvalConfig(BaseModel):
    """[eval] section of .coderev.toml"""
    recall_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    precision_threshold: float = Field(default=0.70, ge=0.0, le=1.0)


class CodeRevConfig(BaseModel):
    """
    Full .coderev.toml configuration.
    All fields are optional — missing fields fall back to built-in defaults.
    """
    review: ReviewConfig = Field(default_factory=ReviewConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    exclude: ExcludeConfig = Field(default_factory=ExcludeConfig)
    eval: EvalConfig = Field(default_factory=EvalConfig)

    @classmethod
    def default(cls) -> "CodeRevConfig":
        """Return a config with all built-in defaults."""
        return cls()


# ── Explain Models ────────────────────────────────────────────────────


class ExplainResult(BaseModel):
    """Expanded explanation of a single finding."""
    finding_id: str
    finding: Finding
    what_is_this: str
    why_vulnerable: str
    how_to_fix: str
    real_world_examples: list[str] = []
    references: list[str]
    generated_at: str


# ===== END coderev\schema.py =====

# ===== BEGIN coderev\utils.py =====
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
# Last updated: 2026-03-06 — verify at https://console.groq.com/docs/models
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "moonshotai/kimi-k2-instruct": (0.0000014, 0.0000014),       # $1.40/M tokens in+out (same rate)
    "meta-llama/llama-4-scout-17b-16e-instruct": (0.0000001, 0.0000001),
    "qwen/qwen3-32b": (0.0000009, 0.0000009),
    "default": (0.0000014, 0.0000014),                             # fallback for unknown models
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
    input_rate, output_rate = MODEL_PRICING.get(model, MODEL_PRICING["default"])
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


def build_diff_position_map(diff: str) -> dict[tuple[str, int], int]:
    """Build a mapping from (file_path, file_line_number) to diff_position.

    GitHub's PR comment API requires diff_position (1-indexed position within
    the diff output), not actual file line numbers. This function parses the
    diff to build the mapping so findings can be placed inline correctly.

    Handles renamed files: when a diff contains ``rename from old_name.py`` /
    ``rename to new_name.py``, entries are stored under *both* paths so that
    findings referencing either the old or new name resolve correctly.

    Returns:
        dict mapping (file_path, line_number) to diff_position
    """
    position_map: dict[tuple[str, int], int] = {}
    current_file: str | None = None
    diff_position = 0
    current_file_line = 0

    # Track rename pairs so we can duplicate entries under the old name
    rename_from: str | None = None
    rename_aliases: dict[str, str] = {}  # new_name -> old_name

    for line in diff.split("\n"):
        # Detect rename headers *before* the +++ line
        rename_from_match = re.match(r"^rename from (.+)$", line)
        if rename_from_match:
            rename_from = rename_from_match.group(1)
            diff_position += 1
            continue

        rename_to_match = re.match(r"^rename to (.+)$", line)
        if rename_to_match and rename_from is not None:
            rename_aliases[rename_to_match.group(1)] = rename_from
            rename_from = None
            diff_position += 1
            continue

        file_match = re.match(r"^\+\+\+ b/(.+)$", line)
        if file_match:
            current_file = file_match.group(1)
            diff_position += 1
            continue

        hunk_match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
        if hunk_match:
            current_file_line = int(hunk_match.group(1)) - 1
            diff_position += 1
            continue

        if current_file is None:
            diff_position += 1
            continue

        if line.startswith("+"):
            current_file_line += 1
            diff_position += 1
            position_map[(current_file, current_file_line)] = diff_position
            # Alias: also store under old name so findings using it resolve
            if current_file in rename_aliases:
                position_map[(rename_aliases[current_file], current_file_line)] = diff_position
        elif line.startswith("-"):
            diff_position += 1
        elif line.startswith(" "):
            current_file_line += 1
            diff_position += 1
            position_map[(current_file, current_file_line)] = diff_position
            if current_file in rename_aliases:
                position_map[(rename_aliases[current_file], current_file_line)] = diff_position
        elif line.startswith("diff ") or line.startswith("index ") or line.startswith("---"):
            diff_position += 1

    return position_map


# ===== END coderev\utils.py =====

# ===== BEGIN coderev\config.py =====
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


# ===== END coderev\config.py =====

# ===== BEGIN coderev\chunker.py =====
"""AST-aware diff chunker.

Splits large diffs at function/class boundaries so each chunk
sent to a review agent contains complete, coherent code units.
"""

import re
from dataclasses import dataclass


@dataclass
class DiffChunk:
    """A single chunk of a diff, split at a safe boundary."""

    content: str
    file_paths: list[str]
    chunk_index: int
    total_chunks: int
    start_line: int
    end_line: int

    @property
    def is_single_chunk(self) -> bool:
        return self.total_chunks == 1


class ASTChunker:
    """Splits git diffs into chunks that respect Python AST boundaries.

    Falls back to heuristic splitting for non-Python files.

    Design principle: it is always better to include a little too much
    context in a chunk than to cut a function in half.
    """

    MAX_CHUNK_LINES = 300
    MAX_CHUNK_CHARS = 12_000

    def chunk(self, diff: str) -> list[DiffChunk]:
        """Split *diff* into a list of DiffChunk objects.

        If the diff is small enough, returns a single chunk.
        """
        lines = diff.split("\n")

        if len(lines) <= self.MAX_CHUNK_LINES:
            files = self._extract_files(diff)
            return [
                DiffChunk(
                    content=diff,
                    file_paths=files,
                    chunk_index=0,
                    total_chunks=1,
                    start_line=0,
                    end_line=len(lines),
                )
            ]

        return self._split_by_file_then_function(diff)

    # ── internal helpers ──────────────────────────────────────────────

    def _split_by_file_then_function(self, diff: str) -> list[DiffChunk]:
        file_sections = self._split_by_file(diff)
        raw_chunks: list[tuple[str, str]] = []

        for file_path, section in file_sections.items():
            section_line_count = section.count("\n")
            if file_path.endswith(".py") and section_line_count > self.MAX_CHUNK_LINES:
                sub_sections = self._split_python_at_boundaries(section, file_path)
                # If Python splitting didn't help (no boundaries found), fall back
                if len(sub_sections) == 1 and section_line_count > self.MAX_CHUNK_LINES:
                    sub_sections = self._split_by_lines(section, file_path)
                raw_chunks.extend(sub_sections)
            elif section_line_count > self.MAX_CHUNK_LINES:
                # Non-Python files: split by line count
                raw_chunks.extend(self._split_by_lines(section, file_path))
            else:
                raw_chunks.append((file_path, section))

        return self._pack_into_chunks(raw_chunks)

    def _split_by_file(self, diff: str) -> dict[str, str]:
        """Parse diff into ``{file_path: file_diff_section}``."""
        sections: dict[str, str] = {}
        current_file: str | None = None
        current_lines: list[str] = []

        for line in diff.split("\n"):
            match = re.match(r"^diff --git a/.+ b/(.+)$", line)
            if match:
                if current_file and current_lines:
                    sections[current_file] = "\n".join(current_lines)
                current_file = match.group(1)
                current_lines = [line]
            elif current_file:
                current_lines.append(line)

        if current_file and current_lines:
            sections[current_file] = "\n".join(current_lines)

        return sections

    def _split_python_at_boundaries(
        self, file_diff: str, file_path: str
    ) -> list[tuple[str, str]]:
        """Split a large Python file diff at function/class definition lines."""
        def_pattern = re.compile(r"^[+ ]( {0,8})(def |class |async def )", re.MULTILINE)
        lines = file_diff.split("\n")
        boundary_indices: list[int] = []

        for i, line in enumerate(lines):
            if def_pattern.match(line):
                boundary_indices.append(i)

        if not boundary_indices:
            return [(file_path, file_diff)]

        sections: list[tuple[str, str]] = []
        prev = 0
        for boundary in boundary_indices[1:]:
            section = "\n".join(lines[prev:boundary])
            if section.strip():
                sections.append((file_path, section))
            prev = boundary

        final = "\n".join(lines[prev:])
        if final.strip():
            sections.append((file_path, final))

        return sections if sections else [(file_path, file_diff)]

    def _split_by_lines(
        self, section: str, file_path: str
    ) -> list[tuple[str, str]]:
        """Fallback: split a section at MAX_CHUNK_LINES boundaries."""
        lines = section.split("\n")
        parts: list[tuple[str, str]] = []
        for i in range(0, len(lines), self.MAX_CHUNK_LINES):
            chunk_text = "\n".join(lines[i : i + self.MAX_CHUNK_LINES])
            if chunk_text.strip():
                parts.append((file_path, chunk_text))
        return parts if parts else [(file_path, section)]

    def _pack_into_chunks(
        self, sections: list[tuple[str, str]]
    ) -> list[DiffChunk]:
        """Greedy bin-pack sections into chunks within size limits."""
        chunks: list[tuple[str, list[str], int, int]] = []
        current_content: list[str] = []
        current_files: list[str] = []
        current_lines = 0
        current_chars = 0
        start_line = 0

        for file_path, section in sections:
            section_lines = section.count("\n")
            section_chars = len(section)

            if current_content and (
                current_lines + section_lines > self.MAX_CHUNK_LINES
                or current_chars + section_chars > self.MAX_CHUNK_CHARS
            ):
                chunks.append(
                    (
                        "\n".join(current_content),
                        list(set(current_files)),
                        start_line,
                        start_line + current_lines,
                    )
                )
                start_line += current_lines
                current_content = []
                current_files = []
                current_lines = 0
                current_chars = 0

            current_content.append(section)
            current_files.append(file_path)
            current_lines += section_lines
            current_chars += section_chars

        if current_content:
            chunks.append(
                (
                    "\n".join(current_content),
                    list(set(current_files)),
                    start_line,
                    start_line + current_lines,
                )
            )

        total = len(chunks)
        return [
            DiffChunk(
                content=content,
                file_paths=files,
                chunk_index=i,
                total_chunks=total,
                start_line=start_l,
                end_line=end_l,
            )
            for i, (content, files, start_l, end_l) in enumerate(chunks)
        ]

    def _extract_files(self, diff: str) -> list[str]:
        return re.findall(r"^diff --git a/.+ b/(.+)$", diff, re.MULTILINE)


# ===== END coderev\chunker.py =====

# ===== BEGIN coderev\cache.py =====
"""Local file-based chunk cache.

Keyed by SHA-256(chunk_content + agent_name + model_name).
Stores results at ~/.coderev/cache/ with a configurable TTL.
"""

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path


class ChunkCache:
    """Cache AI review results locally so unchanged chunks are free on re-run.

    Location: ``~/.coderev/cache/``
    Default TTL: 24 hours
    """

    DEFAULT_CACHE_DIR = Path.home() / ".coderev" / "cache"
    DEFAULT_TTL_HOURS = 24

    def __init__(
        self,
        cache_dir: Path | None = None,
        ttl_hours: int = DEFAULT_TTL_HOURS,
    ):
        self.cache_dir = cache_dir or self.DEFAULT_CACHE_DIR
        self.ttl = timedelta(hours=ttl_hours)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._hits = 0
        self._misses = 0

    # ── public API ────────────────────────────────────────────────────

    def get(
        self, chunk_content: str, agent_name: str, model: str
    ) -> list[dict] | None:
        """Return cached findings if available and fresh, else ``None``."""
        path = self._cache_path(self._key(chunk_content, agent_name, model))

        if not path.exists():
            self._misses += 1
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            cached_at = datetime.fromisoformat(data["cached_at"])

            if datetime.now() - cached_at > self.ttl:
                path.unlink()
                self._misses += 1
                return None

            self._hits += 1
            return data["findings"]
        except (json.JSONDecodeError, KeyError, ValueError):
            path.unlink(missing_ok=True)
            self._misses += 1
            return None

    def set(
        self,
        chunk_content: str,
        agent_name: str,
        model: str,
        findings: list[dict],
    ) -> None:
        """Store *findings* in the cache."""
        path = self._cache_path(self._key(chunk_content, agent_name, model))
        data = {
            "cached_at": datetime.now().isoformat(),
            "agent": agent_name,
            "model": model,
            "findings": findings,
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def clear(self) -> int:
        """Delete all cache entries. Returns count deleted."""
        count = 0
        for f in self.cache_dir.glob("*.json"):
            f.unlink()
            count += 1
        return count

    @property
    def stats(self) -> dict:
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / max(1, self._hits + self._misses),
            "cache_dir": str(self.cache_dir),
            "entry_count": len(list(self.cache_dir.glob("*.json"))),
        }

    # ── internals ─────────────────────────────────────────────────────

    def _key(self, chunk_content: str, agent_name: str, model: str) -> str:
        raw = f"{agent_name}:{model}:{chunk_content}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"


# ===== END coderev\cache.py =====

# ===== BEGIN coderev\agent.py =====
"""Groq AI agents for code review.

This module contains the intelligence layer — agents that send diffs
to Kimi K2 via Groq and receive structured code review feedback.

BaseAgent provides shared infrastructure (client, retries, JSON parsing).
CodeReviewAgent is the Week 1 general-purpose reviewer.
Week 2 adds SecurityAgent, LogicAgent, ArchitectureAgent, SynthesisAgent.
"""

import json
import time
from typing import Optional

import groq


# System prompt for the general-purpose code review agent
GENERAL_REVIEW_PROMPT = """You are an expert code reviewer running on Kimi K2.

PRIMARY TASK:
Review only the provided diff and return structured findings for:
security, performance, correctness, style, and test_coverage.

KIMI K2 OUTPUT PROTOCOL (strict):
1. Return a single JSON object only.
2. No markdown, no code fences, no commentary text.
3. Use double-quoted JSON keys/strings only.
4. If a field is unknown, omit it (do not invent values).
5. Do not include metadata; metadata is injected by the application.

EVIDENCE RULES:
- Report only issues that are directly supported by diff evidence.
- If line numbers are uncertain, omit line_range.
- Prefer fewer precise findings over many speculative findings.
- Consolidate duplicate findings on the same root issue.

SEVERITY:
- critical: clearly exploitable vuln, auth bypass, or data-loss risk
- high: likely production bug or major degradation
- medium: realistic edge-case issue
- low: minor improvement
- info: best-practice note

CONFIDENCE (0.0-1.0):
- 1.0 only when the issue is explicit in the diff.
- 0.7-0.9 for strong but context-dependent signals.
- 0.3-0.6 for weak evidence.

PRAISE:
- Include 0-3 specific praise items only when clearly earned.
- If none are credible, return an empty list.

TEST COVERAGE:
- If new non-trivial logic appears without visible tests in the diff,
  add a low-severity test_coverage finding with a concrete test suggestion.
"""


# ── Base Agent ────────────────────────────────────────────────────────


class BaseAgent:
    """Shared Groq client, retry logic, and response parsing.

    All specialized agents (security, logic, architecture, synthesis)
    inherit from this class and override the system prompt and/or schema.
    """

    SYSTEM_PROMPT: str = ""  # Must be overridden by subclass
    DEFAULT_MODEL: str = "moonshotai/kimi-k2-instruct"
    MAX_TOKENS = 4096

    def __init__(
        self,
        api_key: str,
        model: str = None,
        max_retries: int = 2,
    ):
        """Initialize the agent.

        Args:
            api_key: Groq API key
            model: Model to use (default: moonshotai/kimi-k2-instruct)
            max_retries: Number of retries for rate-limit errors
        """
        self.client = groq.Groq(api_key=api_key)
        self.model = model or self.DEFAULT_MODEL
        self.max_retries = max_retries
        self._last_input_tokens: int = 0
        self._last_output_tokens: int = 0

    def _call_llm(self, user_message: str, system_prompt: str = None, max_tokens: int = None) -> str:
        """Core LLM call with retry logic.

        Args:
            user_message: The user message containing the diff/task
            system_prompt: Override system prompt (defaults to self.SYSTEM_PROMPT)
            max_tokens: Override max tokens (defaults to self.MAX_TOKENS)

        Returns:
            Raw string response from the model.
        """
        prompt = system_prompt or self.SYSTEM_PROMPT
        tokens = max_tokens or self.MAX_TOKENS
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=tokens,
                    temperature=0.0,  # deterministic JSON output for Kimi K2
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": user_message},
                    ],
                )
                self._last_input_tokens = response.usage.prompt_tokens
                self._last_output_tokens = response.usage.completion_tokens
                return response.choices[0].message.content
            except groq.RateLimitError as e:
                last_error = e
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
                continue
            except groq.APIError:
                raise

        if last_error:
            raise last_error

    def _parse_json(self, raw: str) -> dict:
        """Strip markdown fences and parse JSON defensively.

        Raises ValueError with helpful message if parsing fails.
        """
        cleaned = (
            raw.strip()
            .removeprefix("```json")
            .removeprefix("```")
            .removesuffix("```")
            .strip()
        )
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Model returned invalid JSON. First 200 chars: {cleaned[:200]}"
            ) from e

    def review(self, diff: str, file_paths: list[str]) -> list[dict]:
        """Override in subclasses to return a list of raw finding dicts.

        The orchestrator collects these and merges them.
        """
        raise NotImplementedError

    @property
    def last_token_usage(self) -> tuple[int, int]:
        """Return (input_tokens, output_tokens) from the last API call."""
        return (self._last_input_tokens, self._last_output_tokens)


# ── General-purpose Code Review Agent ─────────────────────────────────


class CodeReviewAgent(BaseAgent):
    """General-purpose code review agent (Week 1).

    Sends the full diff in a single API call and returns a
    CodeReviewResult validated by Pydantic.
    """

    SYSTEM_PROMPT = GENERAL_REVIEW_PROMPT

    def review(
        self,
        diff: str,
        file_paths: list[str],
        additional_context: Optional[str] = None,
    ) -> CodeReviewResult:
        """Perform a code review on a git diff.

        Args:
            diff: The git diff content to review
            file_paths: List of file paths in the diff
            additional_context: Optional extra context for the review

        Returns:
            CodeReviewResult with findings, metadata, and praise

        Raises:
            groq.APIError: If the API call fails after retries
            pydantic.ValidationError: If the response doesn't match schema
        """
        start = time.time()

        schema_for_ai = self._get_response_schema()

        languages = detect_languages_in_diff(diff)
        lang_context = f"Languages detected: {', '.join(languages)}" if languages else ""

        user_message = self._build_user_message(
            diff=diff,
            file_paths=file_paths,
            schema=schema_for_ai,
            languages_context=lang_context,
            additional_context=additional_context,
        )

        raw = self._call_llm(user_message)
        elapsed = time.time() - start

        return self._parse_response(raw, diff, file_paths, elapsed)

    def _get_response_schema(self) -> dict:
        """JSON schema the AI must follow (metadata excluded)."""
        return {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "One-line verdict summarizing the review",
                },
                "overall_risk": {
                    "type": "string",
                    "enum": ["critical", "high", "medium", "low", "info"],
                    "description": "Overall risk level based on most severe finding",
                },
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "category": {
                                "type": "string",
                                "enum": [
                                    "security", "performance", "correctness",
                                    "style", "test_coverage",
                                ],
                            },
                            "severity": {
                                "type": "string",
                                "enum": ["critical", "high", "medium", "low", "info"],
                            },
                            "file_path": {"type": "string"},
                            "line_range": {
                                "type": "object",
                                "properties": {
                                    "start": {"type": "integer"},
                                    "end": {"type": "integer"},
                                },
                                "required": ["start", "end"],
                            },
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "suggested_fix": {"type": "string"},
                            "references": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "confidence": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                            },
                        },
                        "required": [
                            "category", "severity", "file_path",
                            "title", "description", "confidence",
                        ],
                    },
                },
                "praise": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "1-3 specific things done well",
                },
            },
            "required": ["summary", "overall_risk", "findings", "praise"],
        }

    def _build_user_message(
        self,
        diff: str,
        file_paths: list[str],
        schema: dict,
        languages_context: str,
        additional_context: Optional[str] = None,
    ) -> str:
        """Build the user message for the API call."""
        parts = [
            "Review this git diff:",
            "",
            f"Files changed: {', '.join(file_paths)}",
        ]

        if languages_context:
            parts.append(languages_context)

        if additional_context:
            parts.append(f"\nAdditional context: {additional_context}")

        parts.extend([
            "",
            "<diff>",
            diff,
            "</diff>",
            "",
            "Important: return only raw JSON matching the schema.",
            "Do not wrap in markdown fences and do not add prose.",
            "",
            "Respond with JSON matching this schema:",
            json.dumps(schema, indent=2),
        ])

        return "\n".join(parts)

    def _parse_response(
        self,
        raw: str,
        diff: str,
        file_paths: list[str],
        elapsed: float,
    ) -> CodeReviewResult:
        """Parse and validate the API response."""
        data = self._parse_json(raw)

        input_tokens, output_tokens = self.last_token_usage
        data["metadata"] = {
            "model": self.model,
            "total_tokens": input_tokens + output_tokens,
            "processing_time_seconds": round(elapsed, 2),
            "diff_lines": count_diff_lines(diff),
            "files_reviewed": len(file_paths),
        }

        return CodeReviewResult.model_validate(data)


# ── Exceptions ────────────────────────────────────────────────────────


class AgentError(Exception):
    """Base exception for agent errors."""
    pass


class SchemaValidationError(AgentError):
    """Raised when the model's response doesn't match the expected schema."""
    pass


class APIError(AgentError):
    """Raised when the Groq API returns an error."""
    pass


# ===== END coderev\agent.py =====

# ===== BEGIN coderev\agents\security.py =====
"""SecurityAgent — focused exclusively on security vulnerabilities."""

import json


class SecurityAgent(BaseAgent):
    """Finds only security vulnerabilities. Nothing else.

    Produces higher-quality security findings than a generalist agent
    because the prompt is calibrated for security reasoning only.
    """

    SYSTEM_PROMPT = """You are a security reviewer running on Kimi K2.

TASK:
Find security vulnerabilities only. Ignore style/performance/correctness unless
the issue is directly security-relevant.

KIMI K2 JSON RULES:
- Return only a JSON array.
- No markdown fences, no prose, no extra keys.
- category must always be \"security\".

EVIDENCE RULES:
- Use only evidence visible in the diff.
- If line range is uncertain, omit line_range.
- No speculative findings without concrete indicators.

SEVERITY:
- critical: directly exploitable / breach-level risk
- high: strong exploit path with constraints
- medium: realistic but conditional exploit path
- low: hardening recommendation
- info: security best-practice note

CONFIDENCE:
- 1.0 only for explicit vulnerabilities.
- 0.7-0.9 for likely but context-dependent cases.
- 0.3-0.6 for weak evidence.

REFERENCES:
- Include CWE and OWASP references when applicable.
- suggested_fix should be code, not prose.
"""

    def review(self, diff: str, file_paths: list[str]) -> list[dict]:
        schema_example = {
            "category": "security",
            "severity": "critical|high|medium|low|info",
            "file_path": "path/to/file.py",
            "line_range": {"start": 10, "end": 15},
            "title": "Precise vulnerability title",
            "description": "What the vulnerability is and why it's dangerous",
            "suggested_fix": "actual_code_snippet()",
            "references": ["CWE-89", "OWASP A03:2021"],
            "confidence": 0.95,
        }

        user_message = (
            "Review this diff for security vulnerabilities only.\n\n"
            f"Files: {', '.join(file_paths)}\n\n"
            f"<diff>\n{diff}\n</diff>\n\n"
            "Return a JSON array of findings. Each finding must match this shape:\n"
            f"{json.dumps(schema_example, indent=2)}\n\n"
            "If no security issues found, return an empty array: []"
        )

        raw = self._call_llm(user_message)
        parsed = self._parse_json(raw)

        if not isinstance(parsed, list):
            raise ValueError(f"SecurityAgent expected JSON array, got: {type(parsed)}")

        return parsed


# ===== END coderev\agents\security.py =====

# ===== BEGIN coderev\agents\logic.py =====
"""LogicAgent — focused on correctness, edge cases, and defensive programming."""


class LogicAgent(BaseAgent):
    """Finds logic errors, missing error handling, and edge case failures.

    Catches bugs that will actually crash or misbehave in production.
    """

    SYSTEM_PROMPT = """You are a correctness reviewer running on Kimi K2.

TASK:
Find correctness bugs, edge-case failures, and missing defensive handling.
Do not report security or style findings.

KIMI K2 JSON RULES:
- Return only a JSON array.
- No markdown or explanatory text.
- category must always be \"correctness\".

EVIDENCE RULES:
- Report only issues grounded in the provided diff.
- Omit line_range if uncertain.
- Prefer one precise issue over many speculative ones.

SEVERITY:
- critical: likely crash/data corruption in normal usage
- high: common-edge-case failure or incorrect behavior
- medium: realistic but narrower edge-case failure
- low: unlikely edge-case but valid guardrail
- info: defensive best-practice note

CONFIDENCE:
- 1.0 only when failure is explicit.
- 0.7-0.9 for likely context-dependent bugs.
- 0.3-0.6 for weak evidence.

suggested_fix must be code-level and directly actionable.
"""

    def review(self, diff: str, file_paths: list[str]) -> list[dict]:
        user_message = (
            "Review this diff for logic errors and correctness issues only.\n\n"
            f"Files: {', '.join(file_paths)}\n\n"
            f"<diff>\n{diff}\n</diff>\n\n"
            "Return a JSON array of correctness findings. "
            "Each must have: category, severity, file_path, line_range, title, "
            "description, suggested_fix, references, confidence.\n"
            "category must always be \"correctness\".\n"
            "If none found, return: []"
        )

        raw = self._call_llm(user_message)
        parsed = self._parse_json(raw)
        if not isinstance(parsed, list):
            raise ValueError(f"LogicAgent expected JSON array, got: {type(parsed)}")
        return parsed


# ===== END coderev\agents\logic.py =====

# ===== BEGIN coderev\agents\performance.py =====
"""PerformanceAgent — focused on performance issues that cause real degradation."""


class PerformanceAgent(BaseAgent):
    """Finds performance issues that would cause measurable degradation.

    Avoids micro-optimization noise — only reports meaningful impact.
    """

    SYSTEM_PROMPT = """You are a performance reviewer running on Kimi K2.

TASK:
Find meaningful performance issues in the diff.
Do not report security or correctness findings.

KIMI K2 JSON RULES:
- Return only a JSON array.
- No markdown, no commentary.
- category must always be \"performance\".

EVIDENCE RULES:
- Report only issues supported by the diff.
- Omit line_range if uncertain.
- Avoid speculative micro-optimizations.

SEVERITY:
- critical: likely timeout/OOM under normal production load
- high: major latency or memory regression under realistic load
- medium: noticeable degradation at scale
- low: minor inefficiency
- info: optional optimization note

CONFIDENCE:
- 1.0 for explicit algorithmic or query anti-patterns.
- 0.7-0.9 for likely context-dependent regressions.
- 0.3-0.6 for weak evidence.

When possible, quantify impact (complexity, query count, memory behavior).
suggested_fix should be code-level.
"""

    def review(self, diff: str, file_paths: list[str]) -> list[dict]:
        user_message = (
            "Review this diff for performance issues only.\n\n"
            f"Files: {', '.join(file_paths)}\n\n"
            f"<diff>\n{diff}\n</diff>\n\n"
            "Return a JSON array of performance findings. "
            "Each must have: category, severity, file_path, line_range, title, "
            "description, suggested_fix, references, confidence.\n"
            "category must always be \"performance\".\n"
            "If none found, return: []"
        )

        raw = self._call_llm(user_message)
        parsed = self._parse_json(raw)
        if not isinstance(parsed, list):
            raise ValueError(f"PerformanceAgent expected JSON array, got: {type(parsed)}")
        return parsed


# ===== END coderev\agents\performance.py =====

# ===== BEGIN coderev\agents\synthesizer.py =====
"""SynthesisAgent — deduplicates and ranks findings from all specialist agents."""

import json
import uuid


def _normalize_line_range(lr) -> dict | None:
    """Convert various line_range formats to ``{"start": int, "end": int}``."""
    if lr is None:
        return None
    if isinstance(lr, dict) and "start" in lr and "end" in lr:
        return lr
    if isinstance(lr, (list, tuple)) and len(lr) == 2:
        return {"start": int(lr[0]), "end": int(lr[1])}
    if isinstance(lr, str):
        # Handle "[11, 15]" string format
        lr = lr.strip().strip("[]")
        parts = [p.strip() for p in lr.split(",")]
        if len(parts) == 2:
            return {"start": int(parts[0]), "end": int(parts[1])}
    return None


class SynthesisAgent(BaseAgent):
    """Takes raw findings from all specialist agents and produces the final CodeReviewResult.

    Responsibilities:
    1. Deduplicate findings that overlap by (file_path, line_range)
    2. Resolve conflicting severity ratings (take the higher one with a note)
    3. Identify praise — things done well (requires seeing the full diff)
    4. Produce overall_risk and summary
    5. Validate and construct the final CodeReviewResult Pydantic object
    """

    SYSTEM_PROMPT = """You are the synthesis reviewer running on Kimi K2.

TASK:
Merge specialist findings (security, correctness, performance) into one final
review object.

KIMI K2 JSON RULES:
- Return exactly one JSON object.
- No markdown, no prose outside JSON.
- Keep keys exactly as required.

MERGE RULES:
1. Deduplicate same-issue findings at same file/line region.
2. If severities conflict, keep the higher severity.
3. Do not invent new findings that are absent from specialist inputs.
4. Preserve or lower confidence; do not inflate without stronger evidence.

OUTPUT RULES:
- summary: one sentence
- overall_risk: highest severity among final findings, else "info"
- praise: 0-3 specific and credible positives, else []

ANTI-PATTERNS:
- No generic praise.
- No silent dropping of valid findings.
- No severity downgrade without explicit rationale in description.
"""

    def synthesize(
        self,
        all_findings: list[dict],
        diff: str,
        file_paths: list[str],
        metadata: ReviewMetadata,
    ) -> CodeReviewResult:
        """Merge specialist findings into a final CodeReviewResult."""
        user_message = (
            "Here are findings from three specialist reviewers:\n\n"
            "<findings>\n"
            f"{json.dumps(all_findings, indent=2)}\n"
            "</findings>\n\n"
            "Here is the full diff for context (to identify praise):\n"
            f"<diff>\n{diff[:8000]}\n</diff>\n\n"
            f"Files reviewed: {', '.join(file_paths)}\n\n"
            "Synthesize these into a final JSON review object as described "
            "in your instructions."
        )

        raw = self._call_llm(user_message, max_tokens=6000)
        parsed = self._parse_json(raw)

        # Add generated IDs to findings that don't have them
        for f in parsed.get("findings", []):
            if "id" not in f or not f["id"]:
                f["id"] = str(uuid.uuid4())[:8]
            # Normalize line_range — model sometimes returns arrays or strings
            lr = f.get("line_range")
            if lr is not None:
                f["line_range"] = _normalize_line_range(lr)

        # Inject metadata
        parsed["metadata"] = metadata.model_dump()

        return CodeReviewResult.model_validate(parsed)


# ===== END coderev\agents\synthesizer.py =====

# ===== BEGIN coderev\pipeline.py =====
"""Multi-agent review pipeline.

Orchestrates chunking, specialist agents, caching, and synthesis
to produce a single CodeReviewResult.
"""

import time


class ReviewPipeline:
    """Wire together chunker → specialist agents → synthesizer.

    Flow::

        diff → ASTChunker → chunks
        for each chunk:
            SecurityAgent    → security findings  (cached)
            LogicAgent       → logic findings      (cached)
            PerformanceAgent → perf findings       (cached)
        all findings → SynthesisAgent → CodeReviewResult
    """

    def __init__(
        self,
        api_key: str,
        model: str = "moonshotai/kimi-k2-instruct",
        use_cache: bool = True,
        cache_ttl_hours: int = 24,
    ):
        self.model = model
        self.security = SecurityAgent(api_key, model)
        self.logic = LogicAgent(api_key, model)
        self.performance = PerformanceAgent(api_key, model)
        self.synthesizer = SynthesisAgent(api_key, model)
        self.chunker = ASTChunker()
        self.cache = ChunkCache(ttl_hours=cache_ttl_hours) if use_cache else None

        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0

    def run(self, diff: str, file_paths: list[str]) -> CodeReviewResult:
        """Execute the full pipeline and return a validated result."""
        start_time = time.time()

        chunks = self.chunker.chunk(diff)
        all_findings: list[dict] = []

        for chunk in chunks:
            chunk_findings = self._review_chunk(chunk.content, chunk.file_paths)
            all_findings.extend(chunk_findings)

        elapsed = round(time.time() - start_time, 2)

        metadata = ReviewMetadata(
            model=self.model,
            total_tokens=self._total_input_tokens + self._total_output_tokens,
            processing_time_seconds=elapsed,
            diff_lines=count_diff_lines(diff),
            files_reviewed=len(set(file_paths)),
        )

        result = self.synthesizer.synthesize(
            all_findings=all_findings,
            diff=diff,
            file_paths=file_paths,
            metadata=metadata,
        )

        # Accumulate synthesizer tokens
        inp, out = self.synthesizer.last_token_usage
        self._total_input_tokens += inp
        self._total_output_tokens += out
        # Update metadata with final token count
        result.metadata.total_tokens = (
            self._total_input_tokens + self._total_output_tokens
        )

        if self.cache:
            stats = self.cache.stats
            result.metadata.cache_hit_rate = stats["hit_rate"]
            result.metadata.cache_entries_used = stats.get("entry_count", 0)

        return result

    @property
    def last_token_usage(self) -> tuple[int, int]:
        return (self._total_input_tokens, self._total_output_tokens)

    # ── internals ─────────────────────────────────────────────────────

    def _review_chunk(
        self, chunk_content: str, file_paths: list[str]
    ) -> list[dict]:
        """Run all three specialist agents on a single chunk."""
        findings: list[dict] = []

        agents = [
            (self.security, "SecurityAgent"),
            (self.logic, "LogicAgent"),
            (self.performance, "PerformanceAgent"),
        ]

        for agent, agent_name in agents:
            cached = None
            if self.cache:
                cached = self.cache.get(chunk_content, agent_name, self.model)

            if cached is not None:
                findings.extend(cached)
            else:
                try:
                    raw_findings = agent.review(chunk_content, file_paths)

                    # Accumulate tokens
                    inp, out = agent.last_token_usage
                    self._total_input_tokens += inp
                    self._total_output_tokens += out

                    if self.cache:
                        self.cache.set(
                            chunk_content, agent_name, self.model, raw_findings
                        )
                    findings.extend(raw_findings)
                except Exception as e:
                    import sys
                    print(
                        f"Warning: {agent_name} failed on chunk: {e}",
                        file=sys.stderr,
                    )

        return findings


# ===== END coderev\pipeline.py =====

# ===== BEGIN coderev\formatter.py =====
"""Rich terminal output formatter for code review results.

This module handles the UX layer - rendering beautiful, scannable output
in the terminal using the Rich library.
"""

import json
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box


# Severity emoji mapping
SEVERITY_EMOJI = {
    Severity.CRITICAL: "🔴",
    Severity.HIGH: "🟡",
    Severity.MEDIUM: "🟠",
    Severity.LOW: "🔵",
    Severity.INFO: "⚪",
}

# Severity color mapping for Rich
SEVERITY_COLORS = {
    Severity.CRITICAL: "red bold",
    Severity.HIGH: "yellow bold",
    Severity.MEDIUM: "dark_orange",
    Severity.LOW: "blue",
    Severity.INFO: "dim",
}

# Category abbreviations
CATEGORY_ABBREV = {
    Category.SECURITY: "sec",
    Category.PERFORMANCE: "perf",
    Category.CORRECTNESS: "corr",
    Category.STYLE: "style",
    Category.TEST_COVERAGE: "test",
}


class Formatter:
    """Formatter for code review output.
    
    Supports multiple output formats: rich (terminal), JSON, and markdown.
    """
    
    def __init__(self, console: Optional[Console] = None):
        """Initialize the formatter.
        
        Args:
            console: Rich Console instance (creates new one if not provided)
        """
        self.console = console or Console()
    
    def format(
        self,
        result: CodeReviewResult,
        format_type: str = "rich",
        input_tokens: int = 0,
        output_tokens: int = 0
    ) -> str:
        """Format a code review result.
        
        Args:
            result: The CodeReviewResult to format
            format_type: Output format ('rich', 'json', 'markdown')
            input_tokens: Input token count for cost calculation
            output_tokens: Output token count for cost calculation
            
        Returns:
            Formatted string (for json/markdown) or empty string (for rich, prints directly)
        """
        if format_type == "json":
            return self._format_json(result)
        elif format_type == "markdown":
            return self._format_markdown(result, input_tokens, output_tokens)
        else:
            self._format_rich(result, input_tokens, output_tokens)
            return ""
    
    def _format_rich(
        self,
        result: CodeReviewResult,
        input_tokens: int,
        output_tokens: int
    ) -> None:
        """Render rich terminal output."""
        # Header panel
        self._render_header(result)
        
        # Findings grouped by file
        self._render_findings(result)
        
        # Praise section
        self._render_praise(result)
        
        # Footer with summary
        self._render_footer(result, input_tokens, output_tokens)
    
    def _render_header(self, result: CodeReviewResult) -> None:
        """Render the header panel."""
        meta = result.metadata
        
        header_text = Text()
        header_text.append("  CodeRev  ", style="bold cyan")
        header_text.append("•  ", style="dim")
        header_text.append(meta.model, style="dim")
        header_text.append("  •  ", style="dim")
        header_text.append(f"{meta.processing_time_seconds}s", style="dim")
        header_text.append("\n")
        header_text.append(f"  {meta.files_reviewed} files reviewed", style="dim")
        header_text.append("  •  ", style="dim")
        header_text.append(f"{meta.diff_lines:,} diff lines", style="dim")
        
        panel = Panel(
            header_text,
            box=box.ROUNDED,
            padding=(0, 1),
        )
        self.console.print(panel)
        self.console.print()
    
    def _render_findings(self, result: CodeReviewResult) -> None:
        """Render findings grouped by file."""
        if not result.findings:
            self.console.print("[green]✓ No issues found![/green]")
            self.console.print()
            return
        
        # Group findings by file
        findings_by_file: dict[str, list[Finding]] = {}
        for finding in result.findings:
            if finding.file_path not in findings_by_file:
                findings_by_file[finding.file_path] = []
            findings_by_file[finding.file_path].append(finding)
        
        # Render each file's findings
        for file_path, findings in findings_by_file.items():
            self.console.print(f"[bold]📁 {file_path}[/bold]")
            
            for finding in findings:
                self._render_finding(finding)
            
            self.console.print()
    
    def _render_finding(self, finding: Finding) -> None:
        """Render a single finding."""
        emoji = SEVERITY_EMOJI.get(finding.severity, "⚪")
        color = SEVERITY_COLORS.get(finding.severity, "")
        category_abbrev = CATEGORY_ABBREV.get(finding.category, "???")
        
        # First line: severity, category, title, line number
        line_info = ""
        if finding.line_range:
            line_info = f"[dim]{finding.line_range}[/dim]"
        
        severity_text = finding.severity.value.upper()
        
        self.console.print(
            f"  {emoji} [{color}]{severity_text:8}[/{color}] "
            f"[dim]\\[[/dim]{category_abbrev}[dim]][/dim] "
            f"[bold]{finding.title}[/bold]   {line_info}"
        )
        
        # Description
        self.console.print(f"     [dim]{finding.description}[/dim]")
        
        # Suggested fix
        if finding.suggested_fix:
            # Keep fix on single line if short, otherwise wrap
            fix_text = finding.suggested_fix.strip()
            if len(fix_text) < 80 and "\n" not in fix_text:
                self.console.print(f"     [green]Fix:[/green] [cyan]{fix_text}[/cyan]")
            else:
                self.console.print(f"     [green]Fix:[/green]")
                for line in fix_text.split("\n"):
                    self.console.print(f"       [cyan]{line}[/cyan]")
        
        # References and confidence
        refs_and_conf = []
        if finding.references:
            refs_and_conf.append(" · ".join(finding.references))
        refs_and_conf.append(f"[dim]\\[conf: {finding.confidence:.2f}][/dim]")
        
        if refs_and_conf:
            self.console.print(f"     [dim]→[/dim] {' '.join(refs_and_conf)}")
        
        self.console.print()
    
    def _render_praise(self, result: CodeReviewResult) -> None:
        """Render the praise section."""
        if not result.praise:
            return
        
        self.console.print("[bold]✨ What's done well:[/bold]")
        for item in result.praise:
            self.console.print(f"   [green]•[/green] {item}")
        self.console.print()
    
    def _render_footer(
        self,
        result: CodeReviewResult,
        input_tokens: int,
        output_tokens: int
    ) -> None:
        """Render the footer with summary statistics."""
        self.console.print("─" * 54)
        
        # Count findings by severity
        counts = result.count_by_severity()
        
        # Risk level
        risk_color = SEVERITY_COLORS.get(result.overall_risk, "")
        risk_text = result.overall_risk.value.upper()
        
        # Build severity counts string
        severity_parts = []
        for sev in [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW]:
            count = counts[sev]
            if count > 0:
                emoji = SEVERITY_EMOJI[sev]
                severity_parts.append(f"{count} {sev.value}")
        
        severity_str = " · ".join(severity_parts) if severity_parts else "0 findings"
        
        self.console.print(
            f"  [bold]Risk:[/bold] [{risk_color}]{risk_text}[/{risk_color}]  |  "
            f"{severity_str}"
        )
        
        # Score indicator (simple calculation based on findings)
        score = self._calculate_score(result)
        score_style = "green" if score >= 80 else "yellow" if score >= 60 else "red"
        score_indicator = "✓" if score >= 80 else "⚠" if score >= 60 else "✗"
        
        score_message = "All clear!" if score >= 80 else \
                       "Minor issues" if score >= 60 else \
                       "Findings require attention"
        
        self.console.print(
            f"  [bold]Score:[/bold] [{score_style}]{score}/100  {score_indicator}[/{score_style}]  "
            f"{score_message}"
        )
        
        # Cache stats
        if result.metadata.cache_hit_rate > 0:
            cache_info = f"Cache: {result.metadata.cache_hit_rate:.0%} hit"
            self.console.print(f"  [dim]{cache_info}[/dim]")

        # Token usage and cost
        total_tokens = result.metadata.total_tokens
        cost = estimate_cost(input_tokens, output_tokens, result.metadata.model)
        cost_str = format_cost(cost)
        
        self.console.print(
            f"  [dim]Tokens: {total_tokens:,}  ({cost_str})  |  "
            f"Time: {result.metadata.processing_time_seconds}s[/dim]"
        )
    
    def _calculate_score(self, result: CodeReviewResult) -> int:
        """Calculate a simple health score based on findings.
        
        This is a rough heuristic - not a formal metric.
        """
        base_score = 100
        
        # Deduct points based on severity
        deductions = {
            Severity.CRITICAL: 30,
            Severity.HIGH: 15,
            Severity.MEDIUM: 7,
            Severity.LOW: 3,
            Severity.INFO: 1,
        }
        
        for finding in result.findings:
            base_score -= deductions.get(finding.severity, 0)
        
        return max(0, base_score)
    
    def _format_json(self, result: CodeReviewResult) -> str:
        """Format as JSON output."""
        return result.model_dump_json(indent=2)
    
    def _format_markdown(
        self,
        result: CodeReviewResult,
        input_tokens: int,
        output_tokens: int
    ) -> str:
        """Format as Markdown output."""
        lines = []
        
        # Header
        lines.append("# Code Review Results")
        lines.append("")
        meta = result.metadata
        lines.append(f"**Model:** {meta.model} | **Time:** {meta.processing_time_seconds}s")
        lines.append(f"**Files reviewed:** {meta.files_reviewed} | **Diff lines:** {meta.diff_lines:,}")
        lines.append("")
        
        # Summary
        lines.append(f"## Summary")
        lines.append("")
        lines.append(f"> {result.summary}")
        lines.append("")
        lines.append(f"**Overall Risk:** {result.overall_risk.value.upper()}")
        lines.append("")
        
        # Findings
        if result.findings:
            lines.append("## Findings")
            lines.append("")
            
            for finding in result.findings:
                severity_emoji = SEVERITY_EMOJI.get(finding.severity, "⚪")
                lines.append(f"### {severity_emoji} {finding.title}")
                lines.append("")
                lines.append(f"- **Severity:** {finding.severity.value}")
                lines.append(f"- **Category:** {finding.category.value}")
                lines.append(f"- **File:** `{finding.file_path}`")
                if finding.line_range:
                    lines.append(f"- **Lines:** {finding.line_range.start}-{finding.line_range.end}")
                lines.append(f"- **Confidence:** {finding.confidence:.2f}")
                lines.append("")
                lines.append(finding.description)
                lines.append("")
                
                if finding.suggested_fix:
                    lines.append("**Suggested Fix:**")
                    lines.append("```")
                    lines.append(finding.suggested_fix)
                    lines.append("```")
                    lines.append("")
                
                if finding.references:
                    lines.append(f"**References:** {', '.join(finding.references)}")
                    lines.append("")
        else:
            lines.append("## Findings")
            lines.append("")
            lines.append("✅ No issues found!")
            lines.append("")
        
        # Praise
        if result.praise:
            lines.append("## What's Done Well")
            lines.append("")
            for item in result.praise:
                lines.append(f"- {item}")
            lines.append("")
        
        # Footer
        cost = estimate_cost(input_tokens, output_tokens, result.metadata.model)
        lines.append("---")
        lines.append(f"*Tokens: {meta.total_tokens:,} | Cost: {format_cost(cost)}*")
        
        return "\n".join(lines)


def print_rich(
    result: CodeReviewResult,
    input_tokens: int = 0,
    output_tokens: int = 0,
    console: Optional[Console] = None
) -> None:
    """Convenience function to print rich output.
    
    Args:
        result: The CodeReviewResult to print
        input_tokens: Input token count for cost calculation
        output_tokens: Output token count for cost calculation
        console: Optional Rich Console instance
    """
    formatter = Formatter(console)
    formatter.format(result, "rich", input_tokens, output_tokens)


def to_json(result: CodeReviewResult) -> str:
    """Convenience function to convert result to JSON.
    
    Args:
        result: The CodeReviewResult to convert
        
    Returns:
        JSON string representation
    """
    return Formatter().format(result, "json")


def to_markdown(
    result: CodeReviewResult,
    input_tokens: int = 0,
    output_tokens: int = 0
) -> str:
    """Convenience function to convert result to Markdown.
    
    Args:
        result: The CodeReviewResult to convert
        input_tokens: Input token count for cost calculation
        output_tokens: Output token count for cost calculation
        
    Returns:
        Markdown string representation
    """
    return Formatter().format(result, "markdown", input_tokens, output_tokens)


# ===== END coderev\formatter.py =====

# ===== BEGIN coderev\sarif.py =====
"""SARIF 2.1.0 output formatter for CodeRev.

Converts CodeReviewResult into the Static Analysis Results Interchange Format
used by GitHub Code Scanning, CodeQL, Semgrep, and other security tools.
"""

import json
from datetime import datetime, timezone

# SARIF level mapping
SARIF_LEVEL: dict[str, str] = {
    "critical": "error",
    "high": "error",
    "medium": "warning",
    "low": "note",
    "info": "none",
}

RULE_PREFIX: dict[str, str] = {
    "security": "SEC",
    "performance": "PERF",
    "correctness": "CORR",
    "style": "STYLE",
    "test_coverage": "TEST",
}


def _rule_id(finding: Finding, counter: dict[str, int]) -> str:
    """Generate a stable rule ID from category + title.

    Same title always gets the same number within a run.
    Example: "SQL Injection vulnerability" in security -> "SEC001"
    """
    prefix = RULE_PREFIX.get(finding.category.value, "MISC")
    key = f"{prefix}:{finding.title}"
    if key not in counter:
        counter[key] = len(counter) + 1
    return f"{prefix}{counter[key]:03d}"


def _finding_to_rule(finding: Finding, counter: dict[str, int]) -> dict:
    """Convert a Finding into a SARIF rule definition."""
    rid = _rule_id(finding, counter)
    help_uri = None
    for ref in finding.references:
        if ref.startswith("CWE-"):
            cwe_num = ref.split("-")[1]
            help_uri = f"https://cwe.mitre.org/data/definitions/{cwe_num}.html"
            break
        elif ref.startswith("https://"):
            help_uri = ref
            break

    rule: dict = {
        "id": rid,
        "name": finding.title.replace(" ", "").replace("-", ""),
        "shortDescription": {"text": finding.title},
        "fullDescription": {"text": finding.description},
        "properties": {
            "tags": [finding.category.value],
            "severity": finding.severity.value,
            "confidence": finding.confidence,
        },
    }
    if help_uri:
        rule["helpUri"] = help_uri
    return rule


def _finding_to_result(finding: Finding, counter: dict[str, int]) -> dict:
    """Convert a Finding into a SARIF result entry."""
    result: dict = {
        "ruleId": _rule_id(finding, counter),
        "level": SARIF_LEVEL.get(finding.severity.value, "warning"),
        "message": {"text": finding.description},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {
                        "uri": finding.file_path,
                        "uriBaseId": "%SRCROOT%",
                    },
                    "region": {
                        "startLine": finding.line_range.start if finding.line_range else 1,
                        "endLine": finding.line_range.end if finding.line_range else 1,
                    },
                }
            }
        ],
    }

    if finding.suggested_fix:
        result["fixes"] = [
            {
                "description": {"text": finding.suggested_fix},
                "artifactChanges": [],
            }
        ]

    if finding.references:
        related = []
        for ref in finding.references:
            if ref.startswith("CWE-") or ref.startswith("OWASP"):
                related.append({"message": {"text": ref}})
        if related:
            result["relatedLocations"] = related

    return result


def to_sarif(result: CodeReviewResult) -> dict:
    """Convert a CodeReviewResult to a SARIF 2.1.0 document.

    Returns:
        A dict representing the full SARIF document (ready for json.dumps).
    """
    counter: dict[str, int] = {}

    # Deduplicate rules — same title = same rule even across multiple findings
    rules: list[dict] = []
    seen_rule_ids: set[str] = set()
    for finding in result.findings:
        rule = _finding_to_rule(finding, counter)
        if rule["id"] not in seen_rule_ids:
            rules.append(rule)
            seen_rule_ids.add(rule["id"])

    results = [_finding_to_result(f, counter) for f in result.findings]

    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "CodeRev",
                        "version": __version__,
                        "informationUri": "https://github.com/yourusername/coderev",
                        "rules": rules,
                    }
                },
                "results": results,
                "invocations": [
                    {
                        "executionSuccessful": True,
                        "endTimeUtc": datetime.now(timezone.utc).isoformat(),
                        "toolExecutionNotices": [
                            {
                                "message": {
                                    "text": (
                                        f"Model: {result.metadata.model} | "
                                        f"Tokens: {result.metadata.total_tokens:,} | "
                                        f"Time: {result.metadata.processing_time_seconds}s"
                                    )
                                },
                                "level": "note",
                            }
                        ],
                    }
                ],
            }
        ],
    }


def sarif_to_string(result: CodeReviewResult) -> str:
    """Return SARIF document as formatted JSON string."""
    return json.dumps(to_sarif(result), indent=2)


# ===== END coderev\sarif.py =====

# ===== BEGIN coderev\explain.py =====

"""ExplainAgent - generates expanded explanations for a single finding.

The explain command reads findings from ~/.coderev/last_result.json
and produces a detailed, educational explanation of the vulnerability.
"""

from datetime import datetime, timezone
from pathlib import Path


LAST_RESULT_PATH = Path.home() / ".coderev" / "last_result.json"


EXPLAIN_SYSTEM_PROMPT = """You are a senior security engineer and expert code reviewer.

A developer has received an AI-generated code review finding and wants to
understand it deeply. You will receive the finding details and produce an
expanded educational explanation.

Your explanation must have four sections:

WHAT IS THIS?
Explain the vulnerability or issue class in plain language. Assume the developer
knows how to code but may not know this specific vulnerability type. 2-4 sentences.
No jargon without definition.

WHY IS THIS FILE VULNERABLE?
Explain specifically what is wrong in the code shown. Reference the actual
code pattern, variable names, and line numbers from the finding. 2-3 sentences.

HOW TO FIX IT
Provide a concrete before/after code example that fixes the issue. Use the
actual code context from the finding. Make the fix copy-pasteable.
Include a 1-sentence explanation of why the fix is safe.

REAL WORLD IMPACT
Briefly mention 1-2 real CVEs or incidents caused by this exact vulnerability
class. Keep each to one sentence. If you don't know specific CVEs, describe
the realistic attack scenario instead.

OUTPUT CONTRACT:
Respond ONLY with valid JSON. No preamble. No markdown fences.

{
  "what_is_this": "...",
  "why_vulnerable": "...",
  "how_to_fix": "...",
  "real_world_examples": ["...", "..."]
}"""


class ExplainAgent(BaseAgent):
    """
    Generates an expanded explanation for a single code review finding.

    Usage:
        agent = ExplainAgent(api_key="...")
        result = agent.explain(finding)
        print(result.what_is_this)
    """

    SYSTEM_PROMPT = EXPLAIN_SYSTEM_PROMPT

    def explain(self, finding: Finding) -> ExplainResult:
        """Generate expanded explanation for a finding."""
        line_info = ""
        if finding.line_range:
            line_info = f" (lines {finding.line_range.start}-{finding.line_range.end})"

        user_message = f"""Explain this code review finding in detail.

Finding ID: {finding.id}
Category: {finding.category.value}
Severity: {finding.severity.value}
File: {finding.file_path}{line_info}
Title: {finding.title}
Description: {finding.description}
Suggested Fix: {finding.suggested_fix or '(none provided)'}
References: {', '.join(finding.references) if finding.references else '(none)'}
Confidence: {finding.confidence}

Generate a detailed educational explanation of this finding."""

        raw = self._call_llm(user_message, max_tokens=1500)
        parsed = self._parse_json(raw)

        return ExplainResult(
            finding_id=finding.id,
            finding=finding,
            what_is_this=parsed.get("what_is_this", ""),
            why_vulnerable=parsed.get("why_vulnerable", ""),
            how_to_fix=parsed.get("how_to_fix", ""),
            real_world_examples=parsed.get("real_world_examples", []),
            references=finding.references,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )


def save_last_result(result: CodeReviewResult) -> None:
    """
    Save the most recent review result to ~/.coderev/last_result.json.
    Called automatically at the end of every `coderev review` run.
    """
    LAST_RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAST_RESULT_PATH.write_text(result.model_dump_json(indent=2), encoding="utf-8")


def load_last_result() -> CodeReviewResult | None:
    """Load the most recent review result. Returns None if none exists."""
    if not LAST_RESULT_PATH.exists():
        return None
    try:
        return CodeReviewResult.model_validate_json(
            LAST_RESULT_PATH.read_text(encoding="utf-8")
        )
    except Exception:
        return None


def find_finding_by_id(result: CodeReviewResult, finding_id: str) -> Finding | None:
    """
    Find a finding by its ID prefix. Supports partial IDs (first 4+ chars).
    """
    finding_id = finding_id.lower().strip()
    # Exact match first
    for f in result.findings:
        if f.id == finding_id:
            return f
    # Prefix match
    matches = [f for f in result.findings if f.id.startswith(finding_id)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(
            f"Ambiguous ID '{finding_id}' matches {len(matches)} findings: "
            + ", ".join(f.id for f in matches)
            + "\nProvide more characters."
        )
    return None

# ===== END coderev\explain.py =====

# ===== BEGIN coderev\judge.py =====
"""LLM-as-judge for comparing two code review variants.

When you change a prompt, agent instruction, or model version,
run the judge on a set of diffs to determine if the change is
an improvement before shipping it.
"""

import json
from dataclasses import dataclass


JUDGE_SYSTEM_PROMPT = """You are an expert evaluator of AI-generated code reviews.

ROLE:
You will be given two code reviews (Review A and Review B) of the same git diff.
Your job is to evaluate which review is more useful to a developer.

EVALUATION CRITERIA (score each 1-5):
1. Actionability — Does the review give specific, implementable fixes?
   (5 = exact code fixes with line numbers, 1 = vague prose)
2. Accuracy — Are the findings actually real bugs in the code shown?
   (5 = all findings are real issues, 1 = hallucinated or wrong)
3. Completeness — Does the review catch the most important issues?
   (5 = all critical issues found, 1 = major issues missed)
4. False Positive Rate — Does the review avoid flagging non-issues?
   (5 = no false positives, 1 = mostly false positives)
5. Calibration — Are severity levels appropriate to actual risk?
   (5 = perfectly calibrated, 1 = everything is critical or everything is low)

OUTPUT CONTRACT:
Respond ONLY with valid JSON. No preamble. No markdown fences. Raw JSON only.

{
  "winner": "A" | "B" | "tie",
  "scores": {
    "A": {"actionability": 1-5, "accuracy": 1-5, "completeness": 1-5,
          "false_positive_rate": 1-5, "calibration": 1-5, "total": 1-25},
    "B": {"actionability": 1-5, "accuracy": 1-5, "completeness": 1-5,
          "false_positive_rate": 1-5, "calibration": 1-5, "total": 1-25}
  },
  "reasoning": "Two to three sentences explaining why the winner is better.",
  "key_differences": ["specific difference 1", "specific difference 2"],
  "confidence": 0.0-1.0
}

RULES:
- Be objective. Do not favor longer reviews.
- A precise finding with a correct fix beats three vague warnings.
- "tie" is appropriate when both are roughly equivalent in total score.
- If one review hallucinates findings not in the diff, heavily penalize accuracy."""


@dataclass
class JudgeVerdict:
    winner: str             # "A", "B", or "tie"
    score_a: dict
    score_b: dict
    reasoning: str
    key_differences: list[str]
    confidence: float
    raw_response: str


class LLMJudge(BaseAgent):
    """Uses Kimi K2 to evaluate two code reviews of the same diff."""

    SYSTEM_PROMPT = JUDGE_SYSTEM_PROMPT

    def compare(
        self,
        diff: str,
        review_a: dict,
        review_b: dict,
        label_a: str = "Variant A",
        label_b: str = "Variant B",
    ) -> JudgeVerdict:
        """Compare two reviews of the same diff."""
        findings_a = self._format_findings_for_judge(review_a.get("findings", []))
        findings_b = self._format_findings_for_judge(review_b.get("findings", []))

        user_message = f"""Evaluate these two code reviews of the same diff.

<diff>
{diff[:6000]}
</diff>

<review_a label="{label_a}">
Summary: {review_a.get("summary", "")}
Overall Risk: {review_a.get("overall_risk", "")}
Findings ({len(review_a.get("findings", []))} total):
{findings_a}
</review_a>

<review_b label="{label_b}">
Summary: {review_b.get("summary", "")}
Overall Risk: {review_b.get("overall_risk", "")}
Findings ({len(review_b.get("findings", []))} total):
{findings_b}
</review_b>

Evaluate both reviews and return your verdict as JSON."""

        raw = self._call_llm(user_message, max_tokens=2000)
        parsed = self._parse_json(raw)

        return JudgeVerdict(
            winner=parsed.get("winner", "tie"),
            score_a=parsed.get("scores", {}).get("A", {}),
            score_b=parsed.get("scores", {}).get("B", {}),
            reasoning=parsed.get("reasoning", ""),
            key_differences=parsed.get("key_differences", []),
            confidence=parsed.get("confidence", 0.5),
            raw_response=raw,
        )

    def run_tournament(
        self,
        diffs: list[str],
        reviews_a: list[dict],
        reviews_b: list[dict],
        label_a: str = "Variant A",
        label_b: str = "Variant B",
    ) -> dict:
        """Run judge on multiple diffs and aggregate results."""
        verdicts = []
        for diff, rev_a, rev_b in zip(diffs, reviews_a, reviews_b):
            try:
                verdict = self.compare(diff, rev_a, rev_b, label_a, label_b)
                verdicts.append(verdict)
            except Exception as e:
                print(f"  Warning: Judge failed on one diff: {e}")

        if not verdicts:
            return {"error": "No verdicts produced"}

        def _to_key(label: str) -> str:
            """Normalize a label to a safe dict key: no spaces, no parens."""
            import re
            return re.sub(r'[^a-z0-9_]', '_', label.lower()).strip('_')

        wins_a = sum(1 for v in verdicts if v.winner == "A")
        wins_b = sum(1 for v in verdicts if v.winner == "B")
        ties = sum(1 for v in verdicts if v.winner == "tie")

        avg_score_a = sum(v.score_a.get("total", 0) for v in verdicts) / len(verdicts)
        avg_score_b = sum(v.score_b.get("total", 0) for v in verdicts) / len(verdicts)

        recommendation = (
            f"Use {label_a}" if wins_a > wins_b + 1
            else f"Use {label_b}" if wins_b > wins_a + 1
            else "No clear winner — consider more samples"
        )

        return {
            "total_comparisons": len(verdicts),
            f"{_to_key(label_a)}_wins": wins_a,
            f"{_to_key(label_b)}_wins": wins_b,
            "ties": ties,
            f"{_to_key(label_a)}_win_rate": round(wins_a / len(verdicts), 3),
            f"{_to_key(label_b)}_win_rate": round(wins_b / len(verdicts), 3),
            f"avg_score_{_to_key(label_a)}": round(avg_score_a, 2),
            f"avg_score_{_to_key(label_b)}": round(avg_score_b, 2),
            "recommendation": recommendation,
        }

    def _format_findings_for_judge(self, findings: list[dict]) -> str:
        """Format findings list as readable text for the judge prompt."""
        if not findings:
            return "  (no findings)"
        lines = []
        for i, f in enumerate(findings[:15], 1):
            line_info = ""
            if f.get("line_range"):
                lr = f["line_range"]
                line_info = f" L{lr.get('start', '?')}-{lr.get('end', '?')}"
            lines.append(
                f"  {i}. [{f.get('severity','?').upper()}] {f.get('title','?')}"
                f"{line_info} — {f.get('description','')[:100]}"
            )
        if len(findings) > 15:
            lines.append(f"  ... and {len(findings) - 15} more findings")
        return "\n".join(lines)


# ===== END coderev\judge.py =====

# ===== BEGIN coderev\eval.py =====
"""Evaluation runner for measuring CodeRev pipeline quality.

Runs the pipeline against golden test samples and computes metrics:
- Recall: % of expected findings that were caught
- Precision: % of actual findings that matched an expected finding
- Severity accuracy: % of matched findings with correct severity
- Line accuracy: % of matched findings within ±5 lines of expected
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# Severity ordering for "severity_minimum" comparisons
SEVERITY_ORDER = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}

GOLDEN_DIR = Path(__file__).parent.parent / "tests" / "golden"
RESULTS_DIR = Path(__file__).parent.parent / "results"


class EvalRunner:
    """Runs the CodeRev pipeline against golden test samples and measures quality."""

    LINE_TOLERANCE = 5

    def __init__(
        self,
        api_key: str,
        model: str = "moonshotai/kimi-k2-instruct",
        golden_dir: Path = GOLDEN_DIR,
        results_dir: Path = RESULTS_DIR,
        recall_threshold: float = 0.80,
        precision_threshold: float = 0.70,
        use_cache: bool = False,
    ):
        self.pipeline = ReviewPipeline(
            api_key=api_key,
            model=model,
            use_cache=False,  # ALWAYS False — eval must never use cached results
        )
        self.model = model
        self.golden_dir = golden_dir
        self.results_dir = results_dir
        self.recall_threshold = recall_threshold
        self.precision_threshold = precision_threshold
        results_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────

    def run_all(
        self,
        categories: Optional[list[str]] = None,
        verbose: bool = True,
    ) -> EvalSummary:
        """Run eval against all golden samples (or filtered by category)."""
        samples = self._load_golden_samples(categories)

        if not samples:
            raise ValueError(
                f"No golden samples found in {self.golden_dir}. "
                "Run 'coderev eval --list' to see available samples."
            )

        results: list[EvalResult] = []
        run_id = str(uuid.uuid4())[:8]

        for sample in samples:
            if verbose:
                print(f"  Evaluating {sample.id}...", end=" ", flush=True)
            try:
                result = self.evaluate_sample(sample)
                results.append(result)
                if verbose:
                    status = "PASS" if result.recall >= self.recall_threshold else "FAIL"
                    print(f"{status} recall={result.recall:.0%} precision={result.precision:.0%}")
            except Exception as e:
                if verbose:
                    print(f"ERROR: {e}")

        summary = self._compute_summary(run_id, results)
        self._save_to_history(summary, results)
        return summary

    def evaluate_sample(self, sample: GoldenSample) -> EvalResult:
        """Run pipeline on one golden sample and return EvalResult."""
        import time

        diff = self._generate_diff(sample)
        start = time.time()

        review_result = self.pipeline.run(
            diff=diff,
            file_paths=[sample.file_name],
        )

        elapsed = round(time.time() - start, 2)
        inp, out = self.pipeline.last_token_usage

        matches = self._match_findings(
            expected=sample.expected_findings,
            actual=review_result.findings,
            sample=sample,
        )

        matched = [m for m in matches if m.is_match]
        unmatched_actual = self._find_false_positives(
            matches, review_result.findings
        )

        recall = len(matched) / max(1, len(sample.expected_findings))
        precision = (
            len(matched) / max(1, len(review_result.findings))
            if not sample.false_positive_check
            else (1.0 if len([
                f for f in review_result.findings
                if f.severity in (Severity.CRITICAL, Severity.HIGH)
            ]) == 0 else 0.0)
        )

        severity_accurate = [m for m in matched if m.severity_correct]
        severity_accuracy = len(severity_accurate) / max(1, len(matched))

        line_accurate = [m for m in matched if m.line_accurate]
        line_accuracy = len(line_accurate) / max(1, len(matched))

        return EvalResult(
            sample_id=sample.id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            model=self.model,
            pipeline_version=__version__,
            recall=round(recall, 4),
            precision=round(precision, 4),
            severity_accuracy=round(severity_accuracy, 4),
            line_accuracy=round(line_accuracy, 4),
            expected_count=len(sample.expected_findings),
            found_count=len(matched),
            actual_count=len(review_result.findings),
            false_positive_count=len(unmatched_actual),
            matches=matches,
            tokens_used=inp + out,
            cost_usd=estimate_cost(inp, out, self.model),
            processing_time_seconds=elapsed,
        )

    # ── Matching Logic ────────────────────────────────────────────────

    def _match_findings(
        self,
        expected: list[ExpectedFinding],
        actual: list[Finding],
        sample: GoldenSample,
    ) -> list[FindingMatch]:
        """Greedy matching: for each expected finding, find the best actual match."""
        used_actual_ids: set[str] = set()
        matches: list[FindingMatch] = []

        for exp in expected:
            best_match: Optional[Finding] = None
            best_score = -1.0

            for actual_finding in actual:
                if actual_finding.id in used_actual_ids:
                    continue
                score = self._match_score(exp, actual_finding)
                if score > best_score:
                    best_score = score
                    best_match = actual_finding

            if best_match is not None and best_score > 0:
                used_actual_ids.add(best_match.id)
                matches.append(FindingMatch(
                    expected=exp,
                    matched=best_match,
                    is_match=True,
                    severity_correct=self._severity_matches(exp, best_match),
                    line_accurate=self._line_accurate(exp, best_match),
                    confidence_score=best_match.confidence,
                ))
            else:
                matches.append(FindingMatch(
                    expected=exp,
                    matched=None,
                    is_match=False,
                ))

        return matches

    def _match_score(self, exp: ExpectedFinding, actual: Finding) -> float:
        """Score how well an actual finding matches an expected one."""
        if actual.category != exp.category:
            return 0.0

        title_lower = actual.title.lower()
        if not any(kw.lower() in title_lower for kw in exp.title_keywords):
            return 0.0

        score = 1.0

        if self._severity_matches(exp, actual):
            score += 0.5

        if self._line_accurate(exp, actual):
            score += 0.3

        if exp.references_must_include:
            refs_found = sum(
                1 for r in exp.references_must_include
                if any(r in ar for ar in actual.references)
            )
            score += 0.2 * (refs_found / len(exp.references_must_include))

        return score

    def _severity_matches(self, exp: ExpectedFinding, actual: Finding) -> bool:
        """Check if actual severity meets the expected severity requirement."""
        if exp.severity_minimum:
            return SEVERITY_ORDER[actual.severity] >= SEVERITY_ORDER[exp.severity_minimum]
        return actual.severity == exp.severity

    def _line_accurate(self, exp: ExpectedFinding, actual: Finding) -> bool:
        """Check if actual finding's line range is within ±LINE_TOLERANCE of expected."""
        if not exp.line_range_approximate or not actual.line_range:
            return True
        expected_center = (exp.line_range_approximate.start + exp.line_range_approximate.end) / 2
        actual_center = (actual.line_range.start + actual.line_range.end) / 2
        return abs(expected_center - actual_center) <= self.LINE_TOLERANCE

    def _find_false_positives(
        self, matches: list[FindingMatch], actual: list[Finding]
    ) -> list[Finding]:
        """Actual findings that didn't match any expected finding."""
        matched_ids = {m.matched.id for m in matches if m.matched}
        return [f for f in actual if f.id not in matched_ids]

    # ── Golden Sample Loading ─────────────────────────────────────────

    def _load_golden_samples(
        self, categories: Optional[list[str]] = None
    ) -> list[GoldenSample]:
        """Load all .json golden sample files from tests/golden/."""
        samples = []

        for json_path in self.golden_dir.rglob("*.json"):
            if categories:
                if not any(cat in str(json_path) for cat in categories):
                    continue
            try:
                raw = json.loads(json_path.read_text())
                source_path = json_path.parent / raw["file_name"]
                if source_path.exists():
                    raw["source_code"] = source_path.read_text()
                sample = GoldenSample.model_validate(raw)
                samples.append(sample)
            except Exception as e:
                print(f"  Warning: Could not load {json_path}: {e}")

        return sorted(samples, key=lambda s: s.id)

    def _generate_diff(self, sample: GoldenSample) -> str:
        """Generate a synthetic unified diff for a golden sample source file."""
        lines = sample.source_code.splitlines(keepends=True)
        # Ensure last line has newline for proper diff format
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        total = len(lines)
        header = (
            f"diff --git a/{sample.file_name} b/{sample.file_name}\n"
            f"new file mode 100644\n"
            f"index 0000000..1234567\n"
            f"--- /dev/null\n"
            f"+++ b/{sample.file_name}\n"
            f"@@ -0,0 +1,{total} @@\n"
        )
        body = "".join("+" + line for line in lines)
        return header + body

    # ── Results Persistence ───────────────────────────────────────────

    def _compute_summary(
        self, run_id: str, results: list[EvalResult]
    ) -> EvalSummary:
        if not results:
            raise ValueError("No eval results to summarize")

        failed_samples = [
            r.sample_id for r in results
            if r.recall < self.recall_threshold
        ]

        return EvalSummary(
            run_id=run_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            model=self.model,
            pipeline_version=__version__,
            total_samples=len(results),
            samples_passed=len(results) - len(failed_samples),
            samples_failed=failed_samples,
            avg_recall=round(sum(r.recall for r in results) / len(results), 4),
            avg_precision=round(sum(r.precision for r in results) / len(results), 4),
            avg_severity_accuracy=round(
                sum(r.severity_accuracy for r in results) / len(results), 4
            ),
            avg_line_accuracy=round(
                sum(r.line_accuracy for r in results) / len(results), 4
            ),
            avg_tokens_per_sample=round(
                sum(r.tokens_used for r in results) / len(results), 0
            ),
            avg_cost_per_sample=round(
                sum(r.cost_usd for r in results) / len(results), 5
            ),
            total_cost_usd=round(sum(r.cost_usd for r in results), 4),
            recall_threshold=self.recall_threshold,
            precision_threshold=self.precision_threshold,
        )

    def _save_to_history(
        self, summary: EvalSummary, results: list[EvalResult]
    ) -> None:
        """Append this eval run to results/eval_history.json."""
        history_path = self.results_dir / "eval_history.json"

        history = []
        if history_path.exists():
            try:
                history = json.loads(history_path.read_text())
            except json.JSONDecodeError:
                history = []

        history.append({
            "summary": summary.model_dump(),
            "results": [r.model_dump() for r in results],
        })

        # Keep last 50 runs to prevent unbounded growth
        history = history[-50:]
        history_path.write_text(json.dumps(history, indent=2))


# ===== END coderev\eval.py =====

# ===== BEGIN coderev\cli.py =====
"""CLI entry point for CodeRev.

All CLI commands are defined here using Typer.
Commands: review, cache, eval, compare, config, explain, badge, version
"""

import os
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
# Load environment variables from .env file
load_dotenv()

# Create the app
app = typer.Typer(
    name="coderev",
    help="AI-powered code review using Kimi K2",
    add_completion=False,
    no_args_is_help=True,
)

console = Console()


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        console.print(f"CodeRev version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        Optional[bool],
        typer.Option(
            "--version",
            "-v",
            help="Show version and exit",
            callback=version_callback,
            is_eager=True,
        ),
    ] = None,
) -> None:
    """CodeRev - AI-powered code review using Kimi K2."""
    pass


@app.command()
def review(
    diff: Annotated[
        Optional[Path],
        typer.Option(
            "--diff",
            "-d",
            help="Path to .patch or .diff file",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
    files: Annotated[
        Optional[Path],
        typer.Option(
            "--files",
            "-f",
            help="File containing list of changed files (one per line)",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
    model: Annotated[
        Optional[str],
        typer.Option(
            "--model",
            "-m",
            help="Model to use",
        ),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option(
            "--format",
            help="Output format: rich, json, markdown, sarif",
        ),
    ] = None,
    output: Annotated[
        Optional[Path],
        typer.Option(
            "--output",
            "-o",
            help="Save output to file",
        ),
    ] = None,
    fail_on: Annotated[
        Optional[str],
        typer.Option(
            "--fail-on",
            help="Exit with code 1 if severity found (critical, high, medium, low, info)",
        ),
    ] = None,
    min_confidence: Annotated[
        Optional[float],
        typer.Option(
            "--min-confidence",
            help="Filter out findings below this confidence threshold (0.0-1.0)",
            min=0.0,
            max=1.0,
        ),
    ] = None,
    no_cache: Annotated[
        bool,
        typer.Option(
            "--no-cache",
            help="Disable local chunk cache",
        ),
    ] = False,
    context: Annotated[
        Optional[str],
        typer.Option(
            "--context",
            "-c",
            help="Additional context to provide to the reviewer",
        ),
    ] = None,
) -> None:
    """Review a git diff using Kimi K2 AI.
    
    Reads diff from --diff file or stdin (e.g., git diff | coderev review).
    Defaults are read from .coderev.toml when CLI flags are not provided.
    
    Examples:
        coderev review --diff changes.patch
        git diff | coderev review
        coderev review --diff changes.patch --format json --output results.json
    """

    # Load config for defaults
    try:
        cfg = load_config()
    except ValueError:
        cfg = None

    # Apply config defaults for unset flags
    effective_format = format or (cfg.review.format if cfg else "rich")
    effective_fail_on = fail_on or (
        cfg.review.fail_on.value if cfg and cfg.review.fail_on else "critical"
    )
    effective_min_confidence = (
        min_confidence if min_confidence is not None
        else (cfg.review.min_confidence if cfg else 0.0)
    )
    effective_model = model or (cfg.review.model if cfg else "moonshotai/kimi-k2-instruct")
    effective_no_cache = no_cache or (cfg.review.no_cache if cfg else False)

    # Validate format
    valid_formats = ["rich", "json", "markdown", "sarif"]
    if effective_format not in valid_formats:
        console.print(f"[red]Error:[/red] Invalid format '{effective_format}'. Use one of: {', '.join(valid_formats)}")
        raise typer.Exit(1)
    
    # Validate fail-on
    valid_severities = ["critical", "high", "medium", "low", "info"]
    if effective_fail_on.lower() not in valid_severities:
        console.print(f"[red]Error:[/red] Invalid severity '{effective_fail_on}'. Use one of: {', '.join(valid_severities)}")
        raise typer.Exit(1)
    
    # Get API key
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        console.print("[red]Error:[/red] GROQ_API_KEY environment variable not set.")
        console.print("Set it in your .env file or export it: export GROQ_API_KEY=your_key")
        raise typer.Exit(1)

    # Use env override for model if set
    effective_model = os.getenv("CODEREV_MODEL", effective_model)
    
    # Read diff content
    diff_content: Optional[str] = None
    
    if diff:
        try:
            diff_content = read_diff_from_file(diff)
        except Exception as e:
            console.print(f"[red]Error reading diff file:[/red] {e}")
            raise typer.Exit(1)
    else:
        # Try to read from stdin
        diff_content = read_diff_from_stdin()
        if not diff_content:
            console.print("[red]Error:[/red] No diff provided. Use --diff or pipe input via stdin.")
            console.print("Example: git diff | coderev review")
            raise typer.Exit(1)
    
    if not diff_content.strip():
        console.print("[yellow]Warning:[/yellow] Empty diff provided. Nothing to review.")
        raise typer.Exit(0)
    
    # Get file paths
    file_paths: list[str]
    if files:
        try:
            file_paths = read_files_list(files)
        except Exception as e:
            console.print(f"[red]Error reading files list:[/red] {e}")
            raise typer.Exit(1)
    else:
        # Extract from diff headers
        file_paths = extract_files_from_diff(diff_content)
    
    if not file_paths:
        console.print("[yellow]Warning:[/yellow] Could not extract file paths from diff.")
        file_paths = ["unknown"]
    
    # Show progress for rich format
    if effective_format == "rich":
        console.print(f"[dim]Reviewing {len(file_paths)} file(s) with {effective_model}...[/dim]")
    
    # Initialize pipeline and run review
    try:
        pipeline = ReviewPipeline(
            api_key=api_key,
            model=effective_model,
            use_cache=not effective_no_cache,
        )
        result = pipeline.run(
            diff=diff_content,
            file_paths=file_paths,
        )
        input_tokens, output_tokens = pipeline.last_token_usage
    except Exception as e:
        console.print(f"[red]Error during review:[/red] {e}")
        raise typer.Exit(1)
    
    # Filter findings by confidence
    if effective_min_confidence > 0:
        original_count = len(result.findings)
        result.findings = [
            f for f in result.findings 
            if f.confidence >= effective_min_confidence
        ]
        filtered_count = original_count - len(result.findings)
        if filtered_count > 0 and effective_format == "rich":
            console.print(f"[dim]Filtered {filtered_count} low-confidence finding(s)[/dim]")
    
    # Save result for coderev explain
    try:
        save_last_result(result)
    except Exception:
        pass  # non-critical — don't fail the review

    # SARIF format handled separately — not part of the Formatter class
    if effective_format == "sarif":
        formatted_output = sarif_to_string(result)
        print(formatted_output)
        if output:
            output.write_text(formatted_output, encoding="utf-8")
            console.print(f"[dim]SARIF results saved to {output}[/dim]", stderr=True)
        exit_code = get_severity_exit_code(result.findings, effective_fail_on)
        raise typer.Exit(exit_code)

    # Format output
    formatter = Formatter(console)
    formatted_output = formatter.format(
        result=result,
        format_type=effective_format,
        input_tokens=input_tokens,
        output_tokens=output_tokens
    )
    
    # For json/markdown, print the output (plain print to avoid Rich markup)
    if effective_format in ["json", "markdown"]:
        print(formatted_output)
    
    # Save to file if requested
    if output:
        try:
            if effective_format == "rich":
                # For rich format, save as JSON when writing to file
                file_content = result.model_dump_json(indent=2)
            else:
                file_content = formatted_output
            
            output.write_text(file_content, encoding="utf-8")
            if effective_format == "rich":
                console.print(f"[dim]Results saved to {output}[/dim]")
        except Exception as e:
            console.print(f"[red]Error saving output:[/red] {e}")
            raise typer.Exit(1)
    
    # Determine exit code
    exit_code = get_severity_exit_code(result.findings, effective_fail_on)
    raise typer.Exit(exit_code)


@app.command()
def cache(
    clear: Annotated[
        bool,
        typer.Option("--clear", help="Clear all cached results"),
    ] = False,
    stats: Annotated[
        bool,
        typer.Option("--stats", help="Show cache statistics"),
    ] = False,
) -> None:
    """Manage the local chunk cache."""

    c = ChunkCache()
    if clear:
        count = c.clear()
        console.print(f"Cleared {count} cached entries")
    if stats:
        s = c.stats
        console.print(
            f"Cache: {s['entry_count']} entries | "
            f"Hit rate: {s['hit_rate']:.0%} | "
            f"Dir: {s['cache_dir']}"
        )
    if not clear and not stats:
        console.print("Use --clear or --stats. See: coderev cache --help")


@app.command()
def version() -> None:
    """Show version information."""
    console.print(f"CodeRev version {__version__}")
    console.print("AI-powered code review using Groq (Kimi K2)")


@app.command(name="eval")
def eval_cmd(
    category: Annotated[
        Optional[str],
        typer.Option(
            "--category", "-c",
            help="Run only samples in this category: security|correctness|performance",
        ),
    ] = None,
    threshold: Annotated[
        float,
        typer.Option("--threshold", help="Recall threshold to pass (0.0-1.0)"),
    ] = 0.80,
    list_samples: Annotated[
        bool,
        typer.Option("--list", help="List available golden samples without running"),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose/--quiet"),
    ] = True,
    fail_on_regression: Annotated[
        bool,
        typer.Option("--fail/--no-fail", help="Exit code 1 if recall drops below threshold"),
    ] = True,
) -> None:
    """Run the evaluation suite against golden test samples.

    Measures recall, precision, severity accuracy, and line accuracy.
    Results are saved to results/eval_history.json.

    Examples:
        coderev eval                      # run all samples
        coderev eval --category security  # run only security samples
        coderev eval --list               # show available samples
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        console.print("[red]Error:[/red] GROQ_API_KEY not set", err=True)
        raise typer.Exit(1)

    if list_samples:
        runner = EvalRunner(api_key=api_key)
        samples = runner._load_golden_samples()
        console.print(f"\nAvailable golden samples ({len(samples)} total):\n")
        for s in samples:
            fp_note = " [false positive check]" if s.false_positive_check else ""
            console.print(f"  {s.id}{fp_note}")
            console.print(f"    {s.description}")
            console.print(f"    Expected: {len(s.expected_findings)} finding(s)")
        return

    categories = [category] if category else None

    console.print(f"\n[bold]CodeRev Eval[/bold] — Running against golden samples\n")

    runner = EvalRunner(
        api_key=api_key,
        recall_threshold=threshold,
        precision_threshold=0.70,
    )

    try:
        summary = runner.run_all(categories=categories, verbose=verbose)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}", err=True)
        raise typer.Exit(1)

    console.print(f"\n{'─' * 60}")
    console.print(f"  Eval Summary — {summary.run_id}")
    console.print(f"{'─' * 60}")
    console.print(f"  Samples:    {summary.samples_passed}/{summary.total_samples} passed")
    console.print(f"  Recall:     {summary.avg_recall:.0%}  (threshold: {threshold:.0%})")
    console.print(f"  Precision:  {summary.avg_precision:.0%}")
    console.print(f"  Sev. Acc:   {summary.avg_severity_accuracy:.0%}")
    console.print(f"  Line Acc:   {summary.avg_line_accuracy:.0%}")
    console.print(f"  Cost:       ${summary.total_cost_usd:.4f} total")
    console.print(f"{'─' * 60}")

    if summary.samples_failed:
        console.print(f"\n  [red]Failed samples:[/red]")
        for sid in summary.samples_failed:
            console.print(f"     - {sid}")

    verdict = "[green]PASS[/green]" if summary.passed else "[red]FAIL[/red]"
    console.print(f"\n  {verdict}\n")
    console.print(f"  Results saved to: results/eval_history.json\n")

    if fail_on_regression and not summary.passed:
        raise typer.Exit(1)


@app.command()
def compare(
    diff: Annotated[
        Path,
        typer.Option("--diff", help="Diff file to compare reviews on", exists=True),
    ],
    runs: Annotated[
        int,
        typer.Option("--runs", help="Number of comparison runs (more = more reliable)"),
    ] = 3,
    output: Annotated[
        Optional[Path],
        typer.Option("--output", "-o", help="Save comparison result JSON to file"),
    ] = None,
) -> None:
    """Compare two review variants using LLM-as-judge.

    Runs the same diff through two variants of the pipeline and asks
    the judge which produces better findings.

    Examples:
        coderev compare --diff pr.patch --runs 5
    """
    import json as json_mod

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        console.print("[red]Error:[/red] GROQ_API_KEY not set", err=True)
        raise typer.Exit(1)

    diff_content = diff.read_text()

    console.print(f"\n[bold]CodeRev Compare[/bold] — LLM-as-Judge A/B Test\n")
    console.print(f"  Diff: {diff} ({len(diff_content.splitlines())} lines)")
    console.print(f"  Runs: {runs}\n")

    pipeline_a = ReviewPipeline(api_key=api_key, use_cache=False)
    pipeline_b = ReviewPipeline(api_key=api_key, use_cache=False)

    reviews_a = []
    reviews_b = []

    for i in range(runs):
        console.print(f"  Run {i+1}/{runs}...", end="")
        ra = pipeline_a.run(diff_content, [str(diff)])
        rb = pipeline_b.run(diff_content, [str(diff)])
        reviews_a.append(ra.model_dump())
        reviews_b.append(rb.model_dump())
        console.print(" done")

    judge = LLMJudge(api_key=api_key)
    tournament = judge.run_tournament(
        diffs=[diff_content] * runs,
        reviews_a=reviews_a,
        reviews_b=reviews_b,
        label_a="Variant A (current)",
        label_b="Variant B (new)",
    )

    import re
    def _to_key(label: str) -> str:
        return re.sub(r'[^a-z0-9_]', '_', label.lower()).strip('_')

    key_a = _to_key("Variant A (current)")
    key_b = _to_key("Variant B (new)")

    console.print(f"\n  Results:")
    console.print(f"  Variant A wins: {tournament.get(f'{key_a}_wins', 0)}/{runs}")
    console.print(f"  Variant B wins: {tournament.get(f'{key_b}_wins', 0)}/{runs}")
    console.print(f"  Ties:           {tournament.get('ties', 0)}/{runs}")
    console.print(f"\n  Recommendation: {tournament.get('recommendation', '')}\n")

    if output:
        output.write_text(json_mod.dumps(tournament, indent=2))
        console.print(f"  Saved to: {output}\n")


@app.command()
def config(
    init: Annotated[
        bool,
        typer.Option(
            "--init",
            help="Create a .coderev.toml with commented defaults in the current directory",
        ),
    ] = False,
    validate: Annotated[
        bool,
        typer.Option(
            "--validate",
            help="Validate the current .coderev.toml and show parsed values",
        ),
    ] = False,
    show: Annotated[
        bool,
        typer.Option(
            "--show",
            help="Show the active config (merged from all sources)",
        ),
    ] = False,
) -> None:
    """Manage CodeRev configuration.

    Examples:
        coderev config --init       # create .coderev.toml with defaults
        coderev config --validate   # check your config file for errors
        coderev config --show       # show the active merged config
    """

    if init:
        config_path = Path.cwd() / ".coderev.toml"
        if config_path.exists():
            typer.echo(f".coderev.toml already exists at {config_path}")
            raise typer.Exit(1)
        write_default_config(config_path)
        typer.echo(f"Created {config_path}")
        typer.echo("Edit it to customize your CodeRev settings.")
        return

    if validate:
        project_config = find_project_config()
        if not project_config:
            typer.echo("No .coderev.toml found in this directory or parents.")
            typer.echo("Run 'coderev config --init' to create one.")
            raise typer.Exit(1)
        try:
            cfg = load_config()
            typer.echo(f"{project_config} is valid")
            typer.echo(f"  fail_on:        {cfg.review.fail_on}")
            typer.echo(f"  min_confidence: {cfg.review.min_confidence}")
            typer.echo(f"  format:         {cfg.review.format}")
            typer.echo(f"  agents enabled: {cfg.agents.enabled}")
            if cfg.exclude.paths:
                typer.echo(f"  excluded paths: {cfg.exclude.paths}")
        except ValueError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)
        return

    if show:
        cfg = load_config()
        typer.echo("\nActive CodeRev config (merged from all sources):\n")
        typer.echo(f"  [review]")
        typer.echo(f"    fail_on:        {cfg.review.fail_on or 'none'}")
        typer.echo(f"    min_confidence: {cfg.review.min_confidence}")
        typer.echo(f"    format:         {cfg.review.format}")
        typer.echo(f"    model:          {cfg.review.model}")
        typer.echo(f"    no_cache:       {cfg.review.no_cache}")
        typer.echo(f"  [agents]")
        typer.echo(f"    enabled:        {cfg.agents.enabled}")
        typer.echo(f"  [exclude]")
        typer.echo(f"    paths:          {cfg.exclude.paths or '(none)'}")
        typer.echo(f"    categories:     {[c.value for c in cfg.exclude.categories] or '(none)'}")
        typer.echo(f"  [eval]")
        typer.echo(f"    recall_threshold:    {cfg.eval.recall_threshold}")
        typer.echo(f"    precision_threshold: {cfg.eval.precision_threshold}")
        return

    # Default: show help
    typer.echo("Use --init, --validate, or --show. See: coderev config --help")


@app.command()
def explain(
    finding_id: Annotated[
        str,
        typer.Argument(
            help="Finding ID to explain (full or prefix, e.g. 'a1b2c3d4' or 'a1b2')",
        ),
    ],
    result_file: Annotated[
        Optional[Path],
        typer.Option(
            "--from",
            help="Load findings from this JSON file instead of last review",
            exists=True,
        ),
    ] = None,
) -> None:
    """Get a detailed explanation of a code review finding.

    Finding IDs appear in square brackets in review output: [a1b2c3d4]
    Partial IDs work as long as they're unambiguous: coderev explain a1b2

    Examples:
        coderev explain a1b2c3d4
        coderev explain a1b2
        coderev explain a1b2c3d4 --from my_review.json
    """
    from rich.panel import Panel
    from rich import box

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        console.print("[red]Error:[/red] GROQ_API_KEY not set", err=True)
        raise typer.Exit(1)

    # Load result
    if result_file:
        try:
            result = CodeReviewResult.model_validate_json(result_file.read_text())
        except Exception as e:
            console.print(f"[red]Error:[/red] Could not load {result_file}: {e}", err=True)
            raise typer.Exit(1)
    else:
        result = load_last_result()
        if result is None:
            console.print(
                "[red]Error:[/red] No previous review found.\n"
                "   Run 'coderev review --diff <file>' first, then explain a finding.\n"
                "   Or use --from to specify a review JSON file.",
                err=True,
            )
            raise typer.Exit(1)

    # Find the finding
    try:
        finding = find_finding_by_id(result, finding_id)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}", err=True)
        raise typer.Exit(1)

    if finding is None:
        available = "\n".join(
            f"  [{f.id}] {f.title}" for f in result.findings
        )
        console.print(
            f"[red]Error:[/red] Finding '{finding_id}' not found in last review.\n\n"
            f"Available findings:\n{available}",
            err=True,
        )
        raise typer.Exit(1)

    # Generate explanation
    console.print(f"\n[dim]Generating explanation for [{finding.id}]...[/dim]")

    agent = ExplainAgent(api_key=api_key)
    explanation = agent.explain(finding)

    # Display
    severity_colors = {
        "critical": "bold red",
        "high": "bold orange1",
        "medium": "bold yellow",
        "low": "bold blue",
        "info": "dim",
    }
    sev_style = severity_colors.get(finding.severity.value, "white")
    location = f"{finding.file_path}"
    if finding.line_range:
        location += f":{finding.line_range.start}"

    header = (
        f"[bold]{finding.title}[/bold]\n"
        f"[dim]Category:[/dim] {finding.category.value}  "
        f"[dim]Severity:[/dim] [{sev_style}]{finding.severity.value.upper()}[/{sev_style}]  "
        f"[dim]Location:[/dim] {location}"
    )

    body_parts = [
        f"[bold cyan]WHAT IS THIS?[/bold cyan]\n{explanation.what_is_this}",
        f"[bold cyan]WHY IS THIS VULNERABLE?[/bold cyan]\n{explanation.why_vulnerable}",
        f"[bold cyan]HOW TO FIX IT[/bold cyan]\n{explanation.how_to_fix}",
    ]

    if explanation.real_world_examples:
        examples = "\n".join(f"  {ex}" for ex in explanation.real_world_examples)
        body_parts.append(f"[bold cyan]REAL WORLD IMPACT[/bold cyan]\n{examples}")

    if explanation.references:
        refs = "\n".join(f"  {ref}" for ref in explanation.references)
        body_parts.append(f"[bold cyan]REFERENCES[/bold cyan]\n{refs}")

    body = "\n\n".join(body_parts)

    console.print(Panel(
        f"{header}\n\n{body}",
        title=f"[bold]Finding [{finding.id}][/bold]",
        border_style=sev_style,
        box=box.ROUNDED,
        padding=(1, 2),
    ))
    console.print()


@app.command()
def badge(
    metric: Annotated[
        str,
        typer.Option(
            "--metric",
            help="Metric to show: recall | precision | tests",
        ),
    ] = "recall",
    output: Annotated[
        Optional[Path],
        typer.Option(
            "--output", "-o",
            help="Write badge URL to file",
        ),
    ] = None,
    format: Annotated[
        str,
        typer.Option(
            "--format",
            help="Output format: url | markdown | html",
        ),
    ] = "url",
) -> None:
    """Generate a shields.io quality badge from eval results.

    Reads results/eval_history.json and outputs a badge URL showing
    the latest recall score. Paste into README.md.

    Examples:
        coderev badge
        coderev badge --metric precision
        coderev badge --format markdown
    """
    import json as json_mod
    from urllib.parse import quote

    history_path = Path("results/eval_history.json")
    if not history_path.exists():
        typer.echo(
            "results/eval_history.json not found.\n"
            "Run 'coderev eval' first to generate quality metrics.",
            err=True,
        )
        raise typer.Exit(1)

    history = json_mod.loads(history_path.read_text())
    if not history:
        typer.echo("eval_history.json is empty. Run 'coderev eval' first.", err=True)
        raise typer.Exit(1)

    latest = history[-1]["summary"]

    if metric == "recall":
        value = f"{latest['avg_recall']:.0%}"
        label = "AI Recall"
        color = (
            "brightgreen" if latest["avg_recall"] >= 0.90
            else "green" if latest["avg_recall"] >= 0.80
            else "yellow" if latest["avg_recall"] >= 0.70
            else "red"
        )
    elif metric == "precision":
        value = f"{latest['avg_precision']:.0%}"
        label = "AI Precision"
        color = (
            "brightgreen" if latest["avg_precision"] >= 0.85
            else "green" if latest["avg_precision"] >= 0.70
            else "yellow" if latest["avg_precision"] >= 0.60
            else "red"
        )
    elif metric == "tests":
        import subprocess
        import re as re_mod
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "--ignore=tests/test_agent.py", "-q", "--tb=no"],
            capture_output=True, text=True,
        )
        match = re_mod.search(r"(\d+) passed", proc.stdout)
        count = match.group(1) if match else "?"
        value = f"{count} passing"
        label = "tests"
        color = "brightgreen"
    else:
        typer.echo(f"Unknown metric: {metric}. Use: recall | precision | tests", err=True)
        raise typer.Exit(1)

    # Build shields.io URL
    encoded_label = quote(label)
    encoded_value = quote(value)
    badge_url = f"https://img.shields.io/badge/{encoded_label}-{encoded_value}-{color}"

    if format == "markdown":
        output_str = f"![{label}]({badge_url})"
    elif format == "html":
        output_str = f'<img alt="{label}" src="{badge_url}">'
    else:
        output_str = badge_url

    typer.echo(output_str)

    if output:
        output.write_text(output_str, encoding="utf-8")
        typer.echo(f"\nSaved to: {output}", err=True)


# Entry point for direct execution
if __name__ == "__main__":
    app()


# ===== END coderev\cli.py =====

