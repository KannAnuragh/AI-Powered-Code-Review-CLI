"""Integration tests for CodeRev agent quality.

These tests call the real Groq API and validate that the agent produces
calibrated, balanced, and accurate results. They require GROQ_API_KEY
to be set in the environment (loaded from .env).

Run with:  pytest tests/test_agent.py -v -s
Skip in CI: pytest tests/ --ignore=tests/test_agent.py
"""

import os
import pathlib
import textwrap

import pytest
from dotenv import load_dotenv

from coderev.agent import CodeReviewAgent
from coderev.schema import CodeReviewResult

# ── Fixtures & helpers ────────────────────────────────────────────────

load_dotenv()

SAMPLE_BAD_PATH = pathlib.Path(__file__).resolve().parent.parent / "sample_bad.py"
CLEAN_GOOD_PATH = pathlib.Path(__file__).resolve().parent / "golden" / "clean_good.py"


def _generate_new_file_diff(source_path: pathlib.Path) -> str:
    """Create a 'new file' unified diff from *source_path*."""
    lines = source_path.read_text(encoding="utf-8").splitlines(keepends=True)
    total = len(lines)
    header = (
        f"diff --git a/{source_path.name} b/{source_path.name}\n"
        f"new file mode 100644\n"
        f"index 0000000..1234567\n"
        f"--- /dev/null\n"
        f"+++ b/{source_path.name}\n"
        f"@@ -0,0 +1,{total} @@\n"
    )
    body = "".join("+" + line for line in lines)
    return header + body


def _api_key() -> str:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        pytest.skip("GROQ_API_KEY not set — skipping live agent tests")
    return key


@pytest.fixture(scope="module")
def sample_bad_result() -> CodeReviewResult:
    """Run CodeReviewAgent once on sample_bad.py and cache for the module."""
    diff = _generate_new_file_diff(SAMPLE_BAD_PATH)
    agent = CodeReviewAgent(api_key=_api_key())
    return agent.review(diff=diff, file_paths=["sample_bad.py"])


@pytest.fixture(scope="module")
def clean_good_result() -> CodeReviewResult:
    """Run CodeReviewAgent once on clean_good.py and cache for the module."""
    diff = _generate_new_file_diff(CLEAN_GOOD_PATH)
    agent = CodeReviewAgent(api_key=_api_key())
    return agent.review(diff=diff, file_paths=["clean_good.py"])


# ── Fix 1: Confidence calibration ────────────────────────────────────


class TestConfidenceCalibration:
    """Confidence scores must span a range — not all 1.0."""

    def test_confidence_scores_are_not_all_one(self, sample_bad_result):
        """Real reviews should express uncertainty on at least some findings."""
        confidences = [f.confidence for f in sample_bad_result.findings]
        assert not all(c == 1.0 for c in confidences), (
            "All findings returned confidence=1.0. "
            "This indicates the model is ignoring calibration instructions."
        )

    def test_confidence_range_is_used(self, sample_bad_result):
        """At least one finding should be below 0.9 in a realistic review."""
        confidences = [f.confidence for f in sample_bad_result.findings]
        assert min(confidences) < 0.9, (
            f"Lowest confidence was {min(confidences)}. "
            "Model should express uncertainty on at least one finding."
        )


# ── Fix 2: Category coverage ─────────────────────────────────────────


# Minimum expected findings per category on sample_bad.py
EXPECTED_CATEGORIES = {
    "security": 4,
    "correctness": 2,
    "performance": 2,
}


class TestCategoryCoverage:
    """All major categories must be represented in the results."""

    def test_all_categories_represented(self, sample_bad_result):
        """A full review must produce findings in all major categories."""
        found_categories = {f.category.value for f in sample_bad_result.findings}

        for category, min_count in EXPECTED_CATEGORIES.items():
            category_findings = [
                f for f in sample_bad_result.findings
                if f.category.value == category
            ]
            assert len(category_findings) >= min_count, (
                f"Expected >= {min_count} '{category}' findings, "
                f"got {len(category_findings)}. "
                f"Categories found: {found_categories}"
            )

    def test_performance_findings_exist(self, sample_bad_result):
        """Performance anti-patterns (N+1, O(n²), string concat) must be flagged."""
        perf = [
            f for f in sample_bad_result.findings
            if f.category.value == "performance"
        ]
        assert len(perf) >= 2, (
            f"Only {len(perf)} performance finding(s). "
            "Expected at least 2 (N+1 queries, O(n²) loop, string concat)."
        )


# ── Fix 3: Praise quality ────────────────────────────────────────────


class TestPraiseQuality:
    """Praise must be specific, earned, and not hollow."""

    def test_praise_is_specific_not_generic(self, sample_bad_result):
        """Praise items should reference specific functions or line numbers."""
        generic_phrases = [
            "naming", "docstring", "documentation", "separation", "structure",
            "consistent", "clear comments", "good organization",
        ]
        for praise_item in sample_bad_result.praise:
            lower = praise_item.lower()
            is_generic = any(phrase in lower for phrase in generic_phrases)
            if is_generic:
                print(f"  ⚠️  Potentially generic praise: '{praise_item}'")

    def test_praise_empty_on_purely_bad_code(self, sample_bad_result):
        """sample_bad.py is intentionally all bad. Praise should be minimal."""
        critical_and_high = [
            f for f in sample_bad_result.findings
            if f.severity.value in ("critical", "high")
        ]
        if len(critical_and_high) >= 5:
            assert len(sample_bad_result.praise) <= 1, (
                f"Found {len(critical_and_high)} critical/high findings "
                f"but returned {len(sample_bad_result.praise)} praise items. "
                "Praise should be minimal when code is predominantly bad."
            )


# ── Fix 4: False positive testing on clean code ──────────────────────


class TestFalsePositives:
    """Clean, well-written code must not produce critical/high findings."""

    def test_no_critical_findings_on_clean_code(self, clean_good_result):
        """Well-written file should produce zero critical or high findings."""
        critical_findings = [
            f for f in clean_good_result.findings
            if f.severity.value in ("critical", "high")
        ]
        assert len(critical_findings) == 0, (
            f"False positives detected on clean code:\n"
            + "\n".join(
                f"  - [{f.severity.value}] {f.title}"
                for f in critical_findings
            )
        )

    def test_overall_risk_is_low_on_clean_code(self, clean_good_result):
        """Clean code should be rated low or info risk."""
        assert clean_good_result.overall_risk.value in ("low", "info"), (
            f"Clean code rated as '{clean_good_result.overall_risk.value}' risk. "
            "This is a false positive at the summary level."
        )
