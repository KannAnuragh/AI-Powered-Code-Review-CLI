"""LogicAgent — focused on correctness, edge cases, and defensive programming."""

from ..agent import BaseAgent


class LogicAgent(BaseAgent):
    """Finds logic errors, missing error handling, and edge case failures.

    Catches bugs that will actually crash or misbehave in production.
    """

    SYSTEM_PROMPT = """You are a correctness reviewer running on Kimi K2.

TASK:
Find correctness bugs, edge-case failures, and missing defensive handling.
Do not report security or style findings.

KIMI K2 JSON RULES:
- Return only a JSON array.
- No markdown or explanatory text.
- category must always be \"correctness\".

EVIDENCE RULES:
- Report only issues grounded in the provided diff.
- Omit line_range if uncertain.
- Prefer one precise issue over many speculative ones.

SEVERITY:
- critical: likely crash/data corruption in normal usage
- high: common-edge-case failure or incorrect behavior
- medium: realistic but narrower edge-case failure
- low: unlikely edge-case but valid guardrail
- info: defensive best-practice note

CONFIDENCE:
- 1.0 only when failure is explicit.
- 0.7-0.9 for likely context-dependent bugs.
- 0.3-0.6 for weak evidence.

suggested_fix must be code-level and directly actionable.
"""

    def review(self, diff: str, file_paths: list[str]) -> list[dict]:
        user_message = (
            "Review this diff for logic errors and correctness issues only.\n\n"
            f"Files: {', '.join(file_paths)}\n\n"
            f"<diff>\n{diff}\n</diff>\n\n"
            "Return a JSON array of correctness findings. "
            "Each must have: category, severity, file_path, line_range, title, "
            "description, suggested_fix, references, confidence.\n"
            "category must always be \"correctness\".\n"
            "If none found, return: []"
        )

        raw = self._call_llm(user_message)
        parsed = self._parse_json(raw)
        if not isinstance(parsed, list):
            raise ValueError(f"LogicAgent expected JSON array, got: {type(parsed)}")
        return parsed
