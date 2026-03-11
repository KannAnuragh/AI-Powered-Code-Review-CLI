"""Tests for LLMJudge — mocked LLM calls."""

from unittest.mock import MagicMock, patch
import pytest

from coderev.judge import LLMJudge, JudgeVerdict


MOCK_VERDICT_A_WINS = """{
  "winner": "A",
  "scores": {
    "A": {"actionability": 5, "accuracy": 5, "completeness": 4,
          "false_positive_rate": 5, "calibration": 4, "total": 23},
    "B": {"actionability": 3, "accuracy": 4, "completeness": 3,
          "false_positive_rate": 4, "calibration": 3, "total": 17}
  },
  "reasoning": "Review A provides specific code fixes with line numbers while B gives vague suggestions.",
  "key_differences": ["A has exact parameterized query fix", "B misses the N+1 pattern"],
  "confidence": 0.85
}"""

MOCK_VERDICT_TIE = """{
  "winner": "tie",
  "scores": {
    "A": {"actionability": 4, "accuracy": 4, "completeness": 4,
          "false_positive_rate": 4, "calibration": 4, "total": 20},
    "B": {"actionability": 4, "accuracy": 4, "completeness": 4,
          "false_positive_rate": 4, "calibration": 4, "total": 20}
  },
  "reasoning": "Both reviews are equivalent in quality.",
  "key_differences": [],
  "confidence": 0.6
}"""


def _make_judge():
    with patch("coderev.agent.groq.Groq"):
        return LLMJudge(api_key="test-key")


def _make_review(findings_count: int = 3) -> dict:
    return {
        "summary": "Found issues",
        "overall_risk": "high",
        "findings": [
            {
                "severity": "high",
                "title": f"Finding {i}",
                "description": "Description",
                "line_range": {"start": i, "end": i},
            }
            for i in range(findings_count)
        ],
    }


class TestJudgeCompare:
    def test_returns_verdict_with_winner(self):
        judge = _make_judge()
        judge._call_llm = MagicMock(return_value=MOCK_VERDICT_A_WINS)

        verdict = judge.compare("diff content", _make_review(), _make_review())

        assert isinstance(verdict, JudgeVerdict)
        assert verdict.winner == "A"
        assert verdict.score_a["total"] == 23
        assert verdict.score_b["total"] == 17
        assert "specific code fixes" in verdict.reasoning
        assert verdict.confidence == 0.85

    def test_tie_verdict(self):
        judge = _make_judge()
        judge._call_llm = MagicMock(return_value=MOCK_VERDICT_TIE)

        verdict = judge.compare("diff", _make_review(), _make_review())
        assert verdict.winner == "tie"

    def test_judge_called_with_anonymized_content(self):
        """Judge prompt must not include model names — prevents bias."""
        judge = _make_judge()
        judge._call_llm = MagicMock(return_value=MOCK_VERDICT_A_WINS)

        review_with_model = {**_make_review(), "metadata": {"model": "kimi-k2"}}
        judge.compare("diff", review_with_model, _make_review())

        call_args = judge._call_llm.call_args[0][0]
        assert "kimi-k2" not in call_args

    def test_empty_findings_handled(self):
        judge = _make_judge()
        judge._call_llm = MagicMock(return_value=MOCK_VERDICT_TIE)

        verdict = judge.compare("diff", {"findings": []}, {"findings": []})
        assert verdict.winner == "tie"

    def test_raw_response_preserved(self):
        judge = _make_judge()
        judge._call_llm = MagicMock(return_value=MOCK_VERDICT_A_WINS)

        verdict = judge.compare("diff", _make_review(), _make_review())
        assert verdict.raw_response == MOCK_VERDICT_A_WINS


class TestTournament:
    def test_tournament_aggregates_multiple_runs(self):
        judge = _make_judge()
        judge._call_llm = MagicMock(
            side_effect=[MOCK_VERDICT_A_WINS, MOCK_VERDICT_A_WINS, MOCK_VERDICT_TIE]
        )

        result = judge.run_tournament(
            diffs=["diff1", "diff2", "diff3"],
            reviews_a=[_make_review()] * 3,
            reviews_b=[_make_review()] * 3,
            label_a="Current",
            label_b="New",
        )

        assert result["total_comparisons"] == 3
        assert result["current_wins"] == 2
        assert result["ties"] == 1

    def test_tournament_recommendation_when_clear_winner(self):
        judge = _make_judge()
        judge._call_llm = MagicMock(
            side_effect=[MOCK_VERDICT_A_WINS] * 5
        )

        result = judge.run_tournament(
            diffs=["diff"] * 5,
            reviews_a=[_make_review()] * 5,
            reviews_b=[_make_review()] * 5,
            label_a="Current",
            label_b="New",
        )

        assert "Current" in result["recommendation"]

    def test_tournament_handles_judge_failure_gracefully(self):
        judge = _make_judge()
        judge._call_llm = MagicMock(
            side_effect=[MOCK_VERDICT_A_WINS, ValueError("API error"), MOCK_VERDICT_TIE]
        )

        result = judge.run_tournament(
            diffs=["d1", "d2", "d3"],
            reviews_a=[_make_review()] * 3,
            reviews_b=[_make_review()] * 3,
        )

        assert result["total_comparisons"] == 2

    def test_tournament_all_failures_returns_error(self):
        judge = _make_judge()
        judge._call_llm = MagicMock(side_effect=ValueError("fail"))

        result = judge.run_tournament(
            diffs=["d"],
            reviews_a=[_make_review()],
            reviews_b=[_make_review()],
        )

        assert "error" in result


class TestFindingsFormatting:
    def test_format_with_line_ranges(self):
        judge = _make_judge()
        findings = [
            {"severity": "high", "title": "Issue", "description": "Desc", "line_range": {"start": 10, "end": 20}},
        ]
        text = judge._format_findings_for_judge(findings)
        assert "L10-20" in text
        assert "[HIGH]" in text

    def test_format_caps_at_15(self):
        judge = _make_judge()
        findings = [
            {"severity": "low", "title": f"Issue {i}", "description": "D"}
            for i in range(20)
        ]
        text = judge._format_findings_for_judge(findings)
        assert "and 5 more findings" in text

    def test_format_empty_findings(self):
        judge = _make_judge()
        text = judge._format_findings_for_judge([])
        assert "no findings" in text
