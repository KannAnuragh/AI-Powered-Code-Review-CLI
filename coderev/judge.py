"""LLM-as-judge for comparing two code review variants.

When you change a prompt, agent instruction, or model version,
run the judge on a set of diffs to determine if the change is
an improvement before shipping it.
"""

import json
from dataclasses import dataclass
from .agent import BaseAgent


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
