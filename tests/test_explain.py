"""Tests for CodeRev explain module."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from coderev.explain import (
    LAST_RESULT_PATH,
    ExplainAgent,
    find_finding_by_id,
    load_last_result,
    save_last_result,
)
from coderev.schema import (
    Category,
    CodeReviewResult,
    ExplainResult,
    Finding,
    LineRange,
    ReviewMetadata,
    Severity,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def sample_finding():
    return Finding(
        id="abcd1234",
        category=Category.SECURITY,
        severity=Severity.CRITICAL,
        file_path="auth.py",
        line_range=LineRange(start=47, end=52),
        title="SQL Injection vulnerability",
        description="User input concatenated into SQL query",
        suggested_fix='cursor.execute("SELECT * FROM users WHERE id=?", (uid,))',
        references=["CWE-89"],
        confidence=0.95,
    )


@pytest.fixture
def sample_result(sample_finding):
    return CodeReviewResult(
        metadata=ReviewMetadata(
            model="test-model",
            total_tokens=1000,
            processing_time_seconds=1.0,
            diff_lines=50,
            files_reviewed=1,
        ),
        summary="Found critical issues",
        overall_risk=Severity.CRITICAL,
        findings=[
            sample_finding,
            Finding(
                id="efgh5678",
                category=Category.PERFORMANCE,
                severity=Severity.MEDIUM,
                file_path="utils.py",
                title="N+1 query in loop",
                description="Database query inside for loop",
                confidence=0.8,
            ),
            Finding(
                id="ijkl9012",
                category=Category.CORRECTNESS,
                severity=Severity.LOW,
                file_path="math.py",
                title="Off-by-one error in range",
                description="Range should be inclusive",
                confidence=0.7,
            ),
        ],
    )


# ── ExplainAgent Tests ────────────────────────────────────────────────


class TestExplainAgent:
    """Tests for ExplainAgent."""

    def test_system_prompt_is_set(self):
        """Agent should have the explain system prompt."""
        agent = ExplainAgent(api_key="test")
        assert "WHAT IS THIS" in agent.SYSTEM_PROMPT
        assert "HOW TO FIX" in agent.SYSTEM_PROMPT

    @patch.object(ExplainAgent, "_call_llm")
    @patch.object(ExplainAgent, "_parse_json")
    def test_explain_returns_explain_result(self, mock_parse, mock_llm, sample_finding):
        """explain() should return an ExplainResult."""
        mock_llm.return_value = "{}"
        mock_parse.return_value = {
            "what_is_this": "SQL injection allows attackers to manipulate queries.",
            "why_vulnerable": "User input is concatenated directly into the SQL string.",
            "how_to_fix": "Use parameterized queries.",
            "real_world_examples": ["CVE-2019-12345 allowed data exfiltration."],
        }

        agent = ExplainAgent(api_key="test-key")
        result = agent.explain(sample_finding)

        assert isinstance(result, ExplainResult)
        assert result.finding_id == "abcd1234"
        assert "SQL injection" in result.what_is_this
        assert result.references == ["CWE-89"]
        mock_llm.assert_called_once()


# ── find_finding_by_id Tests ─────────────────────────────────────────


class TestFindFindingById:
    """Tests for finding lookup by ID."""

    def test_exact_match(self, sample_result):
        f = find_finding_by_id(sample_result, "abcd1234")
        assert f is not None
        assert f.id == "abcd1234"

    def test_prefix_match(self, sample_result):
        f = find_finding_by_id(sample_result, "abcd")
        assert f is not None
        assert f.id == "abcd1234"

    def test_not_found_returns_none(self, sample_result):
        assert find_finding_by_id(sample_result, "zzzznnnn") is None

    def test_ambiguous_prefix_raises(self):
        """Ambiguous prefix should raise ValueError."""
        result = CodeReviewResult(
            metadata=ReviewMetadata(
                model="m", total_tokens=0,
                processing_time_seconds=0, diff_lines=0, files_reviewed=0,
            ),
            summary="test",
            overall_risk=Severity.LOW,
            findings=[
                Finding(id="aa001111", category=Category.SECURITY,
                        severity=Severity.LOW, file_path="a.py",
                        title="Finding one title", description="d", confidence=0.5),
                Finding(id="aa002222", category=Category.SECURITY,
                        severity=Severity.LOW, file_path="b.py",
                        title="Finding two title", description="d", confidence=0.5),
            ],
        )
        with pytest.raises(ValueError, match="Ambiguous"):
            find_finding_by_id(result, "aa00")

    def test_case_insensitive(self, sample_result):
        f = find_finding_by_id(sample_result, "ABCD1234")
        assert f is not None
        assert f.id == "abcd1234"


# ── Last Result Persistence Tests ─────────────────────────────────────


class TestLastResultPersistence:
    """Tests for saving/loading review results."""

    def test_save_and_load(self, sample_result, tmp_path, monkeypatch):
        """save then load should roundtrip correctly."""
        fake_path = tmp_path / "last_result.json"
        monkeypatch.setattr("coderev.explain.LAST_RESULT_PATH", fake_path)

        save_last_result(sample_result)
        assert fake_path.exists()

        loaded = load_last_result()
        assert loaded is not None
        assert len(loaded.findings) == len(sample_result.findings)
        assert loaded.findings[0].id == "abcd1234"

    def test_load_returns_none_when_missing(self, tmp_path, monkeypatch):
        """load_last_result should return None when file is missing."""
        fake_path = tmp_path / "nonexistent.json"
        monkeypatch.setattr("coderev.explain.LAST_RESULT_PATH", fake_path)
        assert load_last_result() is None

    def test_load_returns_none_on_corrupt_file(self, tmp_path, monkeypatch):
        """load_last_result should return None if JSON is corrupt."""
        fake_path = tmp_path / "last_result.json"
        fake_path.write_text("not valid json", encoding="utf-8")
        monkeypatch.setattr("coderev.explain.LAST_RESULT_PATH", fake_path)
        assert load_last_result() is None
