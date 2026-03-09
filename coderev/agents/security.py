"""SecurityAgent — focused exclusively on security vulnerabilities."""

import json

from ..agent import BaseAgent


class SecurityAgent(BaseAgent):
    """Finds only security vulnerabilities. Nothing else.

    Produces higher-quality security findings than a generalist agent
    because the prompt is calibrated for security reasoning only.
    """

    SYSTEM_PROMPT = """You are a security reviewer running on Kimi K2.

TASK:
Find security vulnerabilities only. Ignore style/performance/correctness unless
the issue is directly security-relevant.

KIMI K2 JSON RULES:
- Return only a JSON array.
- No markdown fences, no prose, no extra keys.
- category must always be \"security\".

EVIDENCE RULES:
- Use only evidence visible in the diff.
- If line range is uncertain, omit line_range.
- No speculative findings without concrete indicators.

SEVERITY:
- critical: directly exploitable / breach-level risk
- high: strong exploit path with constraints
- medium: realistic but conditional exploit path
- low: hardening recommendation
- info: security best-practice note

CONFIDENCE:
- 1.0 only for explicit vulnerabilities.
- 0.7-0.9 for likely but context-dependent cases.
- 0.3-0.6 for weak evidence.

REFERENCES:
- Include CWE and OWASP references when applicable.
- suggested_fix should be code, not prose.
"""

    def review(self, diff: str, file_paths: list[str]) -> list[dict]:
        schema_example = {
            "category": "security",
            "severity": "critical|high|medium|low|info",
            "file_path": "path/to/file.py",
            "line_range": {"start": 10, "end": 15},
            "title": "Precise vulnerability title",
            "description": "What the vulnerability is and why it's dangerous",
            "suggested_fix": "actual_code_snippet()",
            "references": ["CWE-89", "OWASP A03:2021"],
            "confidence": 0.95,
        }

        user_message = (
            "Review this diff for security vulnerabilities only.\n\n"
            f"Files: {', '.join(file_paths)}\n\n"
            f"<diff>\n{diff}\n</diff>\n\n"
            "Return a JSON array of findings. Each finding must match this shape:\n"
            f"{json.dumps(schema_example, indent=2)}\n\n"
            "If no security issues found, return an empty array: []"
        )

        raw = self._call_llm(user_message)
        parsed = self._parse_json(raw)

        if not isinstance(parsed, list):
            raise ValueError(f"SecurityAgent expected JSON array, got: {type(parsed)}")

        return parsed
