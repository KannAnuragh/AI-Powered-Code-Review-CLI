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

from . import __version__
from .pipeline import ReviewPipeline
from .schema import (
    Category, EvalResult, EvalSummary, ExpectedFinding,
    Finding, FindingMatch, GoldenSample, Severity,
)
from .utils import estimate_cost


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
            use_cache=use_cache,
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
