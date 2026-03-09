"""PerformanceAgent — focused on performance issues that cause real degradation."""

from ..agent import BaseAgent


class PerformanceAgent(BaseAgent):
    """Finds performance issues that would cause measurable degradation.

    Avoids micro-optimization noise — only reports meaningful impact.
    """

    SYSTEM_PROMPT = """You are a performance reviewer running on Kimi K2.

TASK:
Find meaningful performance issues in the diff.
Do not report security or correctness findings.

KIMI K2 JSON RULES:
- Return only a JSON array.
- No markdown, no commentary.
- category must always be \"performance\".

EVIDENCE RULES:
- Report only issues supported by the diff.
- Omit line_range if uncertain.
- Avoid speculative micro-optimizations.

SEVERITY:
- critical: likely timeout/OOM under normal production load
- high: major latency or memory regression under realistic load
- medium: noticeable degradation at scale
- low: minor inefficiency
- info: optional optimization note

CONFIDENCE:
- 1.0 for explicit algorithmic or query anti-patterns.
- 0.7-0.9 for likely context-dependent regressions.
- 0.3-0.6 for weak evidence.

When possible, quantify impact (complexity, query count, memory behavior).
suggested_fix should be code-level.
"""

    def review(self, diff: str, file_paths: list[str]) -> list[dict]:
        user_message = (
            "Review this diff for performance issues only.\n\n"
            f"Files: {', '.join(file_paths)}\n\n"
            f"<diff>\n{diff}\n</diff>\n\n"
            "Return a JSON array of performance findings. "
            "Each must have: category, severity, file_path, line_range, title, "
            "description, suggested_fix, references, confidence.\n"
            "category must always be \"performance\".\n"
            "If none found, return: []"
        )

        raw = self._call_llm(user_message)
        parsed = self._parse_json(raw)
        if not isinstance(parsed, list):
            raise ValueError(f"PerformanceAgent expected JSON array, got: {type(parsed)}")
        return parsed
