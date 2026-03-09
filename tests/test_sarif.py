"""Tests for SARIF output format."""

import json

import pytest

from coderev.sarif import to_sarif, sarif_to_string
from coderev.schema import (
    Category,
    CodeReviewResult,
    Finding,
    LineRange,
    ReviewMetadata,
    Severity,
)


def _make_result(findings=None) -> CodeReviewResult:
    return CodeReviewResult(
        metadata=ReviewMetadata(
            model="moonshotai/kimi-k2-instruct",
            total_tokens=5000,
            processing_time_seconds=3.5,
            diff_lines=100,
            files_reviewed=1,
        ),
        summary="Test review",
        overall_risk=Severity.HIGH,
        findings=findings or [],
    )


class TestSARIFStructure:
    def test_valid_sarif_version(self):
        doc = to_sarif(_make_result())
        assert doc["version"] == "2.1.0"
        assert "$schema" in doc

    def test_has_runs_array(self):
        doc = to_sarif(_make_result())
        assert "runs" in doc
        assert len(doc["runs"]) == 1

    def test_tool_driver_name(self):
        doc = to_sarif(_make_result())
        driver = doc["runs"][0]["tool"]["driver"]
        assert driver["name"] == "CodeRev"
        assert driver["version"] == "0.4.0"

    def test_model_not_in_driver_name(self):
        """Model name must NOT appear in tool.driver.name — breaks GitHub."""
        doc = to_sarif(_make_result())
        driver_name = doc["runs"][0]["tool"]["driver"]["name"]
        assert "kimi" not in driver_name.lower()
        assert "cache" not in driver_name.lower()


class TestSARIFSeverityMapping:
    def test_critical_maps_to_error(self):
        finding = Finding(
            category=Category.SECURITY,
            severity=Severity.CRITICAL,
            file_path="app.py",
            title="SQL Injection found here",
            description="Bad SQL",
            confidence=1.0,
        )
        doc = to_sarif(_make_result([finding]))
        assert doc["runs"][0]["results"][0]["level"] == "error"

    def test_medium_maps_to_warning(self):
        finding = Finding(
            category=Category.PERFORMANCE,
            severity=Severity.MEDIUM,
            file_path="app.py",
            title="N plus one query pattern",
            description="N+1",
            confidence=0.8,
        )
        doc = to_sarif(_make_result([finding]))
        assert doc["runs"][0]["results"][0]["level"] == "warning"

    def test_low_maps_to_note(self):
        finding = Finding(
            category=Category.STYLE,
            severity=Severity.LOW,
            file_path="app.py",
            title="Missing docstring here",
            description="No docs",
            confidence=0.9,
        )
        doc = to_sarif(_make_result([finding]))
        assert doc["runs"][0]["results"][0]["level"] == "note"


class TestSARIFLocations:
    def test_line_range_in_result(self):
        finding = Finding(
            category=Category.SECURITY,
            severity=Severity.HIGH,
            file_path="src/auth.py",
            line_range=LineRange(start=47, end=52),
            title="Path traversal vulnerability",
            description="Unsafe path",
            confidence=0.95,
        )
        doc = to_sarif(_make_result([finding]))
        region = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]
        assert region["startLine"] == 47
        assert region["endLine"] == 52

    def test_missing_line_range_defaults_to_line_one(self):
        finding = Finding(
            category=Category.SECURITY,
            severity=Severity.HIGH,
            file_path="app.py",
            title="Hardcoded secret value",
            description="Secret",
            confidence=0.9,
        )
        doc = to_sarif(_make_result([finding]))
        region = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]
        assert region["startLine"] == 1

    def test_file_path_in_artifact_location(self):
        finding = Finding(
            category=Category.SECURITY,
            severity=Severity.HIGH,
            file_path="src/deep/nested/auth.py",
            title="SQL injection in nested file",
            description="Bad SQL",
            confidence=1.0,
        )
        doc = to_sarif(_make_result([finding]))
        uri = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        assert uri == "src/deep/nested/auth.py"


class TestSARIFRules:
    def test_rules_deduplicated(self):
        """Same title -> same rule ID -> defined once in rules array."""
        finding1 = Finding(
            category=Category.SECURITY,
            severity=Severity.CRITICAL,
            file_path="a.py",
            title="SQL Injection found here",
            description="Bad SQL in a.py",
            confidence=1.0,
        )
        finding2 = Finding(
            category=Category.SECURITY,
            severity=Severity.HIGH,
            file_path="b.py",
            title="SQL Injection found here",
            description="Bad SQL in b.py",
            confidence=0.9,
        )
        doc = to_sarif(_make_result([finding1, finding2]))
        rules = doc["runs"][0]["tool"]["driver"]["rules"]
        rule_ids = [r["id"] for r in rules]
        assert len(rule_ids) == len(set(rule_ids)), "Duplicate rule IDs found"

    def test_cwe_reference_becomes_help_uri(self):
        finding = Finding(
            category=Category.SECURITY,
            severity=Severity.CRITICAL,
            file_path="app.py",
            title="SQL Injection in app",
            description="Bad SQL",
            references=["CWE-89", "OWASP A03:2021"],
            confidence=1.0,
        )
        doc = to_sarif(_make_result([finding]))
        rule = doc["runs"][0]["tool"]["driver"]["rules"][0]
        assert "helpUri" in rule
        assert "89" in rule["helpUri"]

    def test_fix_suggestion_in_result(self):
        finding = Finding(
            category=Category.SECURITY,
            severity=Severity.CRITICAL,
            file_path="app.py",
            title="SQL Injection with fix",
            description="Bad SQL",
            suggested_fix='cursor.execute("SELECT * FROM users WHERE id=?", (uid,))',
            confidence=1.0,
        )
        doc = to_sarif(_make_result([finding]))
        result = doc["runs"][0]["results"][0]
        assert "fixes" in result
        assert len(result["fixes"]) == 1


class TestSARIFSerialization:
    def test_sarif_to_string_is_valid_json(self):
        result = _make_result()
        sarif_str = sarif_to_string(result)
        parsed = json.loads(sarif_str)
        assert parsed["version"] == "2.1.0"

    def test_empty_findings_produces_valid_sarif(self):
        doc = to_sarif(_make_result([]))
        assert doc["runs"][0]["results"] == []
        assert doc["runs"][0]["tool"]["driver"]["rules"] == []
