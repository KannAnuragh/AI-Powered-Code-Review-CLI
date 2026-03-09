"""Tests for the EvalRunner — all mocked, no real API calls."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from coderev.eval import EvalRunner
from coderev.schema import (
    Category, CodeReviewResult, EvalResult, ExpectedFinding,
    Finding, GoldenSample, LineRange, ReviewMetadata, Severity,
)


def _make_sample(id: str = "security/test", false_positive_check: bool = False):
    return GoldenSample(
        id=id,
        description="Test sample",
        file_name="test.py",
        source_code="def get_user(username):\n    query = f\"SELECT * FROM users WHERE username = '{username}'\"\n",
        expected_findings=[
            ExpectedFinding(
                category=Category.SECURITY,
                severity=Severity.CRITICAL,
                title_keywords=["SQL", "injection"],
                line_range_approximate=LineRange(start=2, end=2),
                references_must_include=["CWE-89"],
            )
        ],
        expected_categories=[Category.SECURITY],
        false_positive_check=false_positive_check,
    )


def _make_matching_finding():
    return Finding(
        id="abc12345",
        category=Category.SECURITY,
        severity=Severity.CRITICAL,
        file_path="test.py",
        line_range=LineRange(start=2, end=2),
        title="SQL Injection vulnerability",
        description="f-string in SQL query",
        suggested_fix='cursor.execute("SELECT * FROM users WHERE username = ?", (username,))',
        references=["CWE-89", "OWASP A03:2021"],
        confidence=1.0,
    )


def _make_pipeline_result(findings=None):
    return CodeReviewResult(
        metadata=ReviewMetadata(
            model="moonshotai/kimi-k2-instruct",
            total_tokens=5000,
            processing_time_seconds=3.0,
            diff_lines=10,
            files_reviewed=1,
        ),
        summary="Test result",
        overall_risk=Severity.CRITICAL,
        findings=findings or [],
    )


def _make_runner(tmp_path):
    with patch("coderev.eval.ReviewPipeline"):
        runner = EvalRunner(
            api_key="test-key",
            golden_dir=tmp_path / "golden",
            results_dir=tmp_path / "results",
        )
    return runner


class TestMatchingLogic:
    def test_exact_match_produces_is_match_true(self, tmp_path):
        runner = _make_runner(tmp_path)
        sample = _make_sample()
        finding = _make_matching_finding()
        matches = runner._match_findings(
            expected=sample.expected_findings,
            actual=[finding],
            sample=sample,
        )
        assert len(matches) == 1
        assert matches[0].is_match is True

    def test_wrong_category_no_match(self, tmp_path):
        runner = _make_runner(tmp_path)
        sample = _make_sample()
        finding = _make_matching_finding()
        finding = finding.model_copy(update={"category": Category.PERFORMANCE})
        matches = runner._match_findings(
            expected=sample.expected_findings,
            actual=[finding],
            sample=sample,
        )
        assert matches[0].is_match is False

    def test_missing_title_keyword_no_match(self, tmp_path):
        runner = _make_runner(tmp_path)
        sample = _make_sample()
        finding = _make_matching_finding()
        finding = finding.model_copy(update={"title": "Unrelated performance issue"})
        matches = runner._match_findings(
            expected=sample.expected_findings,
            actual=[finding],
            sample=sample,
        )
        assert matches[0].is_match is False

    def test_line_accuracy_within_tolerance(self, tmp_path):
        runner = _make_runner(tmp_path)
        sample = _make_sample()
        finding = _make_matching_finding()
        finding = finding.model_copy(
            update={"line_range": LineRange(start=5, end=5)}
        )
        matches = runner._match_findings(
            expected=sample.expected_findings,
            actual=[finding],
            sample=sample,
        )
        assert matches[0].line_accurate is True

    def test_line_accuracy_outside_tolerance(self, tmp_path):
        runner = _make_runner(tmp_path)
        sample = _make_sample()
        finding = _make_matching_finding()
        finding = finding.model_copy(
            update={"line_range": LineRange(start=20, end=20)}
        )
        matches = runner._match_findings(
            expected=sample.expected_findings,
            actual=[finding],
            sample=sample,
        )
        assert matches[0].line_accurate is False

    def test_each_actual_finding_matches_at_most_one_expected(self, tmp_path):
        runner = _make_runner(tmp_path)
        sample = _make_sample()
        sample = sample.model_copy(
            update={"expected_findings": sample.expected_findings * 2}
        )
        finding = _make_matching_finding()
        matches = runner._match_findings(
            expected=sample.expected_findings,
            actual=[finding],
            sample=sample,
        )
        matched = [m for m in matches if m.is_match]
        assert len(matched) == 1

    def test_severity_minimum_allows_higher_severity(self, tmp_path):
        runner = _make_runner(tmp_path)
        expected = ExpectedFinding(
            category=Category.SECURITY,
            severity=Severity.HIGH,
            title_keywords=["SQL", "injection"],
            severity_minimum=Severity.HIGH,
        )
        finding = _make_matching_finding()  # severity=CRITICAL
        assert runner._severity_matches(expected, finding) is True

    def test_severity_minimum_rejects_lower_severity(self, tmp_path):
        runner = _make_runner(tmp_path)
        expected = ExpectedFinding(
            category=Category.SECURITY,
            severity=Severity.CRITICAL,
            title_keywords=["SQL", "injection"],
            severity_minimum=Severity.CRITICAL,
        )
        finding = _make_matching_finding()
        finding = finding.model_copy(update={"severity": Severity.MEDIUM})
        assert runner._severity_matches(expected, finding) is False


class TestMetricComputation:
    def test_perfect_recall(self, tmp_path):
        runner = _make_runner(tmp_path)
        sample = _make_sample()
        finding = _make_matching_finding()
        runner.pipeline.run = MagicMock(
            return_value=_make_pipeline_result([finding])
        )
        runner.pipeline.last_token_usage = (1000, 500)
        result = runner.evaluate_sample(sample)
        assert result.recall == 1.0

    def test_zero_recall_when_nothing_found(self, tmp_path):
        runner = _make_runner(tmp_path)
        sample = _make_sample()
        runner.pipeline.run = MagicMock(
            return_value=_make_pipeline_result([])
        )
        runner.pipeline.last_token_usage = (1000, 500)
        result = runner.evaluate_sample(sample)
        assert result.recall == 0.0

    def test_false_positive_counted(self, tmp_path):
        runner = _make_runner(tmp_path)
        sample = _make_sample()
        false_positive = Finding(
            category=Category.STYLE,
            severity=Severity.LOW,
            file_path="test.py",
            title="Style issue unrelated",
            description="A style thing",
            confidence=0.5,
        )
        runner.pipeline.run = MagicMock(
            return_value=_make_pipeline_result(
                [_make_matching_finding(), false_positive]
            )
        )
        runner.pipeline.last_token_usage = (1000, 500)
        result = runner.evaluate_sample(sample)
        assert result.false_positive_count == 1

    def test_false_positive_check_sample(self, tmp_path):
        runner = _make_runner(tmp_path)
        sample = _make_sample(false_positive_check=True)
        sample = sample.model_copy(update={"expected_findings": []})
        runner.pipeline.run = MagicMock(
            return_value=_make_pipeline_result([])
        )
        runner.pipeline.last_token_usage = (1000, 500)
        result = runner.evaluate_sample(sample)
        assert result.precision == 1.0


class TestDiffGeneration:
    def test_generated_diff_has_proper_format(self, tmp_path):
        runner = _make_runner(tmp_path)
        sample = _make_sample()
        diff = runner._generate_diff(sample)
        assert diff.startswith("diff --git")
        assert "+++ b/test.py" in diff
        assert "--- /dev/null" in diff
        assert "@@ -0,0 +1," in diff


class TestResultsPersistence:
    def test_eval_history_created(self, tmp_path):
        runner = _make_runner(tmp_path)
        sample = _make_sample()
        runner.pipeline.run = MagicMock(
            return_value=_make_pipeline_result([_make_matching_finding()])
        )
        runner.pipeline.last_token_usage = (1000, 500)

        result = runner.evaluate_sample(sample)
        summary = runner._compute_summary("test-run", [result])
        runner._save_to_history(summary, [result])

        history_path = tmp_path / "results" / "eval_history.json"
        assert history_path.exists()
        history = json.loads(history_path.read_text())
        assert len(history) == 1
        assert history[0]["summary"]["run_id"] == "test-run"

    def test_history_capped_at_50_runs(self, tmp_path):
        runner = _make_runner(tmp_path)
        sample = _make_sample()
        runner.pipeline.run = MagicMock(
            return_value=_make_pipeline_result([_make_matching_finding()])
        )
        runner.pipeline.last_token_usage = (500, 250)

        for i in range(51):
            result = runner.evaluate_sample(sample)
            summary = runner._compute_summary(f"run-{i}", [result])
            runner._save_to_history(summary, [result])

        history = json.loads(
            (tmp_path / "results" / "eval_history.json").read_text()
        )
        assert len(history) == 50


class TestGoldenSampleLoading:
    def test_loads_samples_from_directory(self, tmp_path):
        runner = _make_runner(tmp_path)
        golden = tmp_path / "golden" / "security"
        golden.mkdir(parents=True)
        (golden / "test.py").write_text("x = 1\n")
        (golden / "test.json").write_text(json.dumps({
            "id": "security/test",
            "description": "Test",
            "file_name": "test.py",
            "expected_findings": [],
            "expected_categories": ["security"],
        }))

        samples = runner._load_golden_samples()
        assert len(samples) == 1
        assert samples[0].id == "security/test"

    def test_category_filter(self, tmp_path):
        runner = _make_runner(tmp_path)
        # Create security sample
        sec = tmp_path / "golden" / "security"
        sec.mkdir(parents=True)
        (sec / "s.py").write_text("x = 1\n")
        (sec / "s.json").write_text(json.dumps({
            "id": "security/s",
            "description": "Sec",
            "file_name": "s.py",
            "expected_findings": [],
            "expected_categories": ["security"],
        }))
        # Create perf sample
        perf = tmp_path / "golden" / "performance"
        perf.mkdir(parents=True)
        (perf / "p.py").write_text("y = 2\n")
        (perf / "p.json").write_text(json.dumps({
            "id": "performance/p",
            "description": "Perf",
            "file_name": "p.py",
            "expected_findings": [],
            "expected_categories": ["performance"],
        }))

        samples = runner._load_golden_samples(categories=["security"])
        assert len(samples) == 1
        assert samples[0].id == "security/s"
