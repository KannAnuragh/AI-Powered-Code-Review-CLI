"""Tests for CodeRev schema module."""

import pytest
from pydantic import ValidationError

from coderev.schema import (
    Category,
    CodeReviewResult,
    EvalResult,
    EvalSummary,
    ExpectedFinding,
    Finding,
    FindingMatch,
    GoldenSample,
    LineRange,
    ReviewMetadata,
    Severity,
)


class TestLineRange:
    """Tests for LineRange model."""
    
    def test_valid_line_range(self):
        """Test creating a valid line range."""
        lr = LineRange(start=10, end=20)
        assert lr.start == 10
        assert lr.end == 20
    
    def test_single_line(self):
        """Test a single-line range."""
        lr = LineRange(start=5, end=5)
        assert str(lr) == "L:5"
    
    def test_multi_line_str(self):
        """Test string representation of multi-line range."""
        lr = LineRange(start=10, end=20)
        assert str(lr) == "L:10–20"
    
    def test_invalid_start_line(self):
        """Test that line numbers must be >= 1."""
        with pytest.raises(ValidationError):
            LineRange(start=0, end=5)
    
    def test_invalid_end_line(self):
        """Test that end line must be >= 1."""
        with pytest.raises(ValidationError):
            LineRange(start=1, end=0)


class TestFinding:
    """Tests for Finding model."""
    
    def test_minimal_finding(self):
        """Test creating a finding with minimal required fields."""
        finding = Finding(
            category=Category.SECURITY,
            severity=Severity.HIGH,
            file_path="src/auth.py",
            title="SQL Injection vulnerability",
            description="User input is concatenated into SQL query",
            confidence=0.95,
        )
        assert finding.category == Category.SECURITY
        assert finding.severity == Severity.HIGH
        assert finding.id  # Auto-generated ID
        assert len(finding.id) == 8
    
    def test_full_finding(self):
        """Test creating a finding with all fields."""
        finding = Finding(
            category=Category.SECURITY,
            severity=Severity.CRITICAL,
            file_path="src/auth.py",
            line_range=LineRange(start=47, end=52),
            title="SQL Injection vulnerability",
            description="User input is concatenated into SQL query",
            suggested_fix='cursor.execute("SELECT * FROM users WHERE id=?", (user_id,))',
            references=["CWE-89", "OWASP A03:2021"],
            confidence=0.97,
        )
        assert finding.line_range.start == 47
        assert len(finding.references) == 2
    
    def test_confidence_bounds(self):
        """Test that confidence must be between 0 and 1."""
        # Valid edge cases
        Finding(
            category=Category.STYLE,
            severity=Severity.INFO,
            file_path="test.py",
            title="Test finding title",
            description="Description",
            confidence=0.0,
        )
        Finding(
            category=Category.STYLE,
            severity=Severity.INFO,
            file_path="test.py",
            title="Test finding title",
            description="Description",
            confidence=1.0,
        )
        
        # Invalid: too low
        with pytest.raises(ValidationError):
            Finding(
                category=Category.STYLE,
                severity=Severity.INFO,
                file_path="test.py",
                title="Test finding title",
                description="Description",
                confidence=-0.1,
            )
        
        # Invalid: too high
        with pytest.raises(ValidationError):
            Finding(
                category=Category.STYLE,
                severity=Severity.INFO,
                file_path="test.py",
                title="Test finding title",
                description="Description",
                confidence=1.5,
            )
    
    def test_title_minimum_length(self):
        """Test that title must have minimum length."""
        with pytest.raises(ValidationError):
            Finding(
                category=Category.STYLE,
                severity=Severity.INFO,
                file_path="test.py",
                title="Bug",  # Too short
                description="Description",
                confidence=0.5,
            )


class TestReviewMetadata:
    """Tests for ReviewMetadata model."""
    
    def test_valid_metadata(self):
        """Test creating valid metadata."""
        meta = ReviewMetadata(
            model="moonshotai/kimi-k2-instruct",
            total_tokens=18432,
            processing_time_seconds=12.4,
            diff_lines=1847,
            files_reviewed=3,
        )
        assert meta.model == "moonshotai/kimi-k2-instruct"
        assert meta.total_tokens == 18432
    
    def test_negative_tokens_invalid(self):
        """Test that token count can't be negative."""
        with pytest.raises(ValidationError):
            ReviewMetadata(
                model="moonshotai/kimi-k2-instruct",
                total_tokens=-100,
                processing_time_seconds=1.0,
                diff_lines=100,
                files_reviewed=1,
            )


class TestCodeReviewResult:
    """Tests for CodeReviewResult model."""
    
    @pytest.fixture
    def sample_metadata(self):
        """Create sample metadata for tests."""
        return ReviewMetadata(
            model="moonshotai/kimi-k2-instruct",
            total_tokens=10000,
            processing_time_seconds=5.0,
            diff_lines=500,
            files_reviewed=2,
        )
    
    @pytest.fixture
    def sample_findings(self):
        """Create sample findings for tests."""
        return [
            Finding(
                category=Category.SECURITY,
                severity=Severity.CRITICAL,
                file_path="auth.py",
                title="SQL Injection vulnerability",
                description="User input in SQL query",
                confidence=0.95,
            ),
            Finding(
                category=Category.PERFORMANCE,
                severity=Severity.MEDIUM,
                file_path="utils.py",
                title="Inefficient loop",
                description="O(n^2) complexity",
                confidence=0.7,
            ),
            Finding(
                category=Category.STYLE,
                severity=Severity.LOW,
                file_path="utils.py",
                title="Missing docstring",
                description="Function lacks documentation",
                confidence=0.9,
            ),
        ]
    
    def test_minimal_result(self, sample_metadata):
        """Test creating a result with minimal fields."""
        result = CodeReviewResult(
            metadata=sample_metadata,
            summary="Code review completed",
            overall_risk=Severity.LOW,
        )
        assert result.findings == []
        assert result.praise == []
    
    def test_full_result(self, sample_metadata, sample_findings):
        """Test creating a complete result."""
        result = CodeReviewResult(
            metadata=sample_metadata,
            summary="Found critical security issues",
            overall_risk=Severity.CRITICAL,
            findings=sample_findings,
            praise=["Good error handling", "Clear variable names"],
        )
        assert len(result.findings) == 3
        assert len(result.praise) == 2
    
    def test_get_findings_by_severity(self, sample_metadata, sample_findings):
        """Test filtering findings by severity."""
        result = CodeReviewResult(
            metadata=sample_metadata,
            summary="Review complete",
            overall_risk=Severity.CRITICAL,
            findings=sample_findings,
        )
        critical = result.get_findings_by_severity(Severity.CRITICAL)
        assert len(critical) == 1
        assert critical[0].title == "SQL Injection vulnerability"
    
    def test_get_findings_by_category(self, sample_metadata, sample_findings):
        """Test filtering findings by category."""
        result = CodeReviewResult(
            metadata=sample_metadata,
            summary="Review complete",
            overall_risk=Severity.CRITICAL,
            findings=sample_findings,
        )
        security = result.get_findings_by_category(Category.SECURITY)
        assert len(security) == 1
    
    def test_has_critical_findings(self, sample_metadata, sample_findings):
        """Test checking for critical findings."""
        result = CodeReviewResult(
            metadata=sample_metadata,
            summary="Review complete",
            overall_risk=Severity.CRITICAL,
            findings=sample_findings,
        )
        assert result.has_critical_findings() is True
        
        # Remove critical finding
        result.findings = [f for f in result.findings if f.severity != Severity.CRITICAL]
        assert result.has_critical_findings() is False
    
    def test_count_by_severity(self, sample_metadata, sample_findings):
        """Test counting findings by severity."""
        result = CodeReviewResult(
            metadata=sample_metadata,
            summary="Review complete",
            overall_risk=Severity.CRITICAL,
            findings=sample_findings,
        )
        counts = result.count_by_severity()
        assert counts[Severity.CRITICAL] == 1
        assert counts[Severity.MEDIUM] == 1
        assert counts[Severity.LOW] == 1
        assert counts[Severity.HIGH] == 0
    
    def test_get_findings_above_confidence(self, sample_metadata, sample_findings):
        """Test filtering by confidence threshold."""
        result = CodeReviewResult(
            metadata=sample_metadata,
            summary="Review complete",
            overall_risk=Severity.CRITICAL,
            findings=sample_findings,
        )
        high_conf = result.get_findings_above_confidence(0.8)
        assert len(high_conf) == 2  # 0.95 and 0.9


class TestEnumValues:
    """Tests for enum consistency."""
    
    def test_severity_values(self):
        """Test that severity enum has expected values."""
        assert Severity.CRITICAL.value == "critical"
        assert Severity.HIGH.value == "high"
        assert Severity.MEDIUM.value == "medium"
        assert Severity.LOW.value == "low"
        assert Severity.INFO.value == "info"
    
    def test_category_values(self):
        """Test that category enum has expected values."""
        assert Category.SECURITY.value == "security"
        assert Category.PERFORMANCE.value == "performance"
        assert Category.CORRECTNESS.value == "correctness"
        assert Category.STYLE.value == "style"
        assert Category.TEST_COVERAGE.value == "test_coverage"


class TestJsonSerialization:
    """Tests for JSON serialization/deserialization."""
    
    def test_finding_json_roundtrip(self):
        """Test that Finding can be serialized and deserialized."""
        finding = Finding(
            id="abc12345",
            category=Category.SECURITY,
            severity=Severity.HIGH,
            file_path="test.py",
            line_range=LineRange(start=10, end=20),
            title="Test finding title",
            description="Test description",
            suggested_fix="some_fix()",
            references=["CWE-123"],
            confidence=0.85,
        )
        
        json_str = finding.model_dump_json()
        restored = Finding.model_validate_json(json_str)
        
        assert restored.id == finding.id
        assert restored.category == finding.category
        assert restored.severity == finding.severity
        assert restored.confidence == finding.confidence
    
    def test_full_result_json_roundtrip(self):
        """Test that full CodeReviewResult can be serialized and deserialized."""
        result = CodeReviewResult(
            metadata=ReviewMetadata(
                model="moonshotai/kimi-k2-instruct",
                total_tokens=5000,
                processing_time_seconds=3.5,
                diff_lines=200,
                files_reviewed=2,
            ),
            summary="Review complete",
            overall_risk=Severity.MEDIUM,
            findings=[
                Finding(
                    category=Category.CORRECTNESS,
                    severity=Severity.MEDIUM,
                    file_path="app.py",
                    title="Off-by-one error",
                    description="Loop iterates one too many times",
                    confidence=0.8,
                )
            ],
            praise=["Good test coverage"],
        )
        
        json_str = result.model_dump_json()
        restored = CodeReviewResult.model_validate_json(json_str)
        
        assert restored.summary == result.summary
        assert len(restored.findings) == 1
        assert restored.findings[0].title == "Off-by-one error"


class TestExpectedFinding:
    """Tests for ExpectedFinding model."""

    def test_minimal_expected_finding(self):
        ef = ExpectedFinding(
            category=Category.SECURITY,
            severity=Severity.CRITICAL,
            title_keywords=["SQL", "injection"],
        )
        assert ef.category == Category.SECURITY
        assert ef.references_must_include == []
        assert ef.line_range_approximate is None
        assert ef.severity_minimum is None

    def test_full_expected_finding(self):
        ef = ExpectedFinding(
            category=Category.SECURITY,
            severity=Severity.CRITICAL,
            title_keywords=["SQL", "injection"],
            line_range_approximate=LineRange(start=10, end=15),
            references_must_include=["CWE-89"],
            severity_minimum=Severity.HIGH,
        )
        assert ef.line_range_approximate.start == 10
        assert ef.references_must_include == ["CWE-89"]
        assert ef.severity_minimum == Severity.HIGH


class TestGoldenSample:
    """Tests for GoldenSample model."""

    def test_valid_golden_sample(self):
        gs = GoldenSample(
            id="security/sql_injection",
            description="SQL injection test",
            file_name="sql_injection.py",
            source_code="import sqlite3\n",
            expected_findings=[
                ExpectedFinding(
                    category=Category.SECURITY,
                    severity=Severity.CRITICAL,
                    title_keywords=["SQL"],
                )
            ],
            expected_categories=[Category.SECURITY],
        )
        assert gs.id == "security/sql_injection"
        assert gs.false_positive_check is False
        assert len(gs.expected_findings) == 1

    def test_false_positive_sample(self):
        gs = GoldenSample(
            id="clean/auth",
            description="Clean auth code",
            file_name="clean_auth.py",
            source_code="import secrets\n",
            expected_findings=[],
            expected_categories=[],
            false_positive_check=True,
        )
        assert gs.false_positive_check is True
        assert gs.expected_findings == []


class TestFindingMatch:
    """Tests for FindingMatch model."""

    def test_unmatched_finding(self):
        fm = FindingMatch(
            expected=ExpectedFinding(
                category=Category.SECURITY,
                severity=Severity.CRITICAL,
                title_keywords=["SQL"],
            ),
        )
        assert fm.is_match is False
        assert fm.matched is None
        assert fm.confidence_score == 0.0

    def test_matched_finding(self):
        finding = Finding(
            category=Category.SECURITY,
            severity=Severity.CRITICAL,
            file_path="test.py",
            title="SQL Injection found",
            description="desc",
            confidence=0.95,
        )
        fm = FindingMatch(
            expected=ExpectedFinding(
                category=Category.SECURITY,
                severity=Severity.CRITICAL,
                title_keywords=["SQL"],
            ),
            matched=finding,
            is_match=True,
            severity_correct=True,
            line_accurate=True,
            confidence_score=0.95,
        )
        assert fm.is_match is True
        assert fm.matched.title == "SQL Injection found"


class TestEvalResult:
    """Tests for EvalResult model."""

    def test_valid_eval_result(self):
        er = EvalResult(
            sample_id="security/sql_injection",
            timestamp="2026-03-09T00:00:00Z",
            model="moonshotai/kimi-k2-instruct",
            pipeline_version="0.4.0",
            recall=1.0,
            precision=0.8,
            severity_accuracy=1.0,
            line_accuracy=0.5,
            expected_count=2,
            found_count=2,
            actual_count=3,
            false_positive_count=1,
            matches=[],
            tokens_used=5000,
            cost_usd=0.01,
            processing_time_seconds=3.5,
        )
        assert er.recall == 1.0
        assert er.false_positive_count == 1

    def test_eval_result_json_roundtrip(self):
        er = EvalResult(
            sample_id="test",
            timestamp="2026-03-09T00:00:00Z",
            model="test-model",
            pipeline_version="0.4.0",
            recall=0.75,
            precision=0.6,
            severity_accuracy=0.5,
            line_accuracy=0.5,
            expected_count=4,
            found_count=3,
            actual_count=5,
            false_positive_count=2,
            matches=[],
            tokens_used=1000,
            cost_usd=0.001,
            processing_time_seconds=1.0,
        )
        json_str = er.model_dump_json()
        restored = EvalResult.model_validate_json(json_str)
        assert restored.sample_id == "test"
        assert restored.recall == 0.75


class TestEvalSummary:
    """Tests for EvalSummary model."""

    def test_passing_summary(self):
        es = EvalSummary(
            run_id="abc123",
            timestamp="2026-03-09T00:00:00Z",
            model="moonshotai/kimi-k2-instruct",
            pipeline_version="0.4.0",
            total_samples=5,
            samples_passed=5,
            samples_failed=[],
            avg_recall=0.90,
            avg_precision=0.85,
            avg_severity_accuracy=0.80,
            avg_line_accuracy=0.75,
            avg_tokens_per_sample=5000.0,
            avg_cost_per_sample=0.01,
            total_cost_usd=0.05,
        )
        assert es.passed is True

    def test_failing_summary_low_recall(self):
        es = EvalSummary(
            run_id="abc123",
            timestamp="2026-03-09T00:00:00Z",
            model="test",
            pipeline_version="0.4.0",
            total_samples=5,
            samples_passed=2,
            samples_failed=["s1", "s2", "s3"],
            avg_recall=0.50,
            avg_precision=0.85,
            avg_severity_accuracy=0.80,
            avg_line_accuracy=0.75,
            avg_tokens_per_sample=5000.0,
            avg_cost_per_sample=0.01,
            total_cost_usd=0.05,
        )
        assert es.passed is False

    def test_failing_summary_low_precision(self):
        es = EvalSummary(
            run_id="abc123",
            timestamp="2026-03-09T00:00:00Z",
            model="test",
            pipeline_version="0.4.0",
            total_samples=3,
            samples_passed=3,
            samples_failed=[],
            avg_recall=0.90,
            avg_precision=0.50,
            avg_severity_accuracy=0.80,
            avg_line_accuracy=0.75,
            avg_tokens_per_sample=5000.0,
            avg_cost_per_sample=0.01,
            total_cost_usd=0.03,
        )
        assert es.passed is False

    def test_custom_thresholds(self):
        es = EvalSummary(
            run_id="abc123",
            timestamp="2026-03-09T00:00:00Z",
            model="test",
            pipeline_version="0.4.0",
            total_samples=1,
            samples_passed=1,
            samples_failed=[],
            avg_recall=0.60,
            avg_precision=0.50,
            avg_severity_accuracy=0.50,
            avg_line_accuracy=0.50,
            avg_tokens_per_sample=1000.0,
            avg_cost_per_sample=0.001,
            total_cost_usd=0.001,
            recall_threshold=0.50,
            precision_threshold=0.40,
        )
        assert es.passed is True

    def test_summary_json_roundtrip(self):
        es = EvalSummary(
            run_id="xyz",
            timestamp="2026-03-09T00:00:00Z",
            model="test",
            pipeline_version="0.4.0",
            total_samples=2,
            samples_passed=1,
            samples_failed=["s1"],
            avg_recall=0.85,
            avg_precision=0.75,
            avg_severity_accuracy=0.90,
            avg_line_accuracy=0.80,
            avg_tokens_per_sample=3000.0,
            avg_cost_per_sample=0.005,
            total_cost_usd=0.01,
        )
        json_str = es.model_dump_json()
        restored = EvalSummary.model_validate_json(json_str)
        assert restored.run_id == "xyz"
        assert restored.passed is True
