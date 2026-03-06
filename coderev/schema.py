"""Pydantic models for structured AI code review output.

This module defines the contract between the AI and the rest of the system.
All agents must conform to these schemas.
"""

from enum import Enum
from typing import Optional
import uuid

from pydantic import BaseModel, Field


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
