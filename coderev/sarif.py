"""SARIF 2.1.0 output formatter for CodeRev.

Converts CodeReviewResult into the Static Analysis Results Interchange Format
used by GitHub Code Scanning, CodeQL, Semgrep, and other security tools.
"""

import json
from datetime import datetime, timezone

from . import __version__
from .schema import CodeReviewResult, Finding

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
