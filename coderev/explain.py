"""ExplainAgent — generates expanded explanations for a single finding.

The explain command reads findings from ~/.coderev/last_result.json
and produces a detailed, educational explanation of the vulnerability.
"""

from datetime import datetime, timezone
from pathlib import Path

from .agent import BaseAgent
from .schema import CodeReviewResult, ExplainResult, Finding


LAST_RESULT_PATH = Path.home() / ".coderev" / "last_result.json"


EXPLAIN_SYSTEM_PROMPT = """You are a senior security engineer and expert code reviewer.

A developer has received an AI-generated code review finding and wants to
understand it deeply. You will receive the finding details and produce an
expanded educational explanation.

Your explanation must have four sections:

WHAT IS THIS?
Explain the vulnerability or issue class in plain language. Assume the developer
knows how to code but may not know this specific vulnerability type. 2-4 sentences.
No jargon without definition.

WHY IS THIS FILE VULNERABLE?
Explain specifically what is wrong in the code shown. Reference the actual
code pattern, variable names, and line numbers from the finding. 2-3 sentences.

HOW TO FIX IT
Provide a concrete before/after code example that fixes the issue. Use the
actual code context from the finding. Make the fix copy-pasteable.
Include a 1-sentence explanation of why the fix is safe.

REAL WORLD IMPACT
Briefly mention 1-2 real CVEs or incidents caused by this exact vulnerability
class. Keep each to one sentence. If you don't know specific CVEs, describe
the realistic attack scenario instead.

OUTPUT CONTRACT:
Respond ONLY with valid JSON. No preamble. No markdown fences.

{
  "what_is_this": "...",
  "why_vulnerable": "...",
  "how_to_fix": "...",
  "real_world_examples": ["...", "..."]
}"""


class ExplainAgent(BaseAgent):
    """
    Generates an expanded explanation for a single code review finding.

    Usage:
        agent = ExplainAgent(api_key="...")
        result = agent.explain(finding)
        print(result.what_is_this)
    """

    SYSTEM_PROMPT = EXPLAIN_SYSTEM_PROMPT

    def explain(self, finding: Finding) -> ExplainResult:
        """Generate expanded explanation for a finding."""
        line_info = ""
        if finding.line_range:
            line_info = f" (lines {finding.line_range.start}-{finding.line_range.end})"

        user_message = f"""Explain this code review finding in detail.

Finding ID: {finding.id}
Category: {finding.category.value}
Severity: {finding.severity.value}
File: {finding.file_path}{line_info}
Title: {finding.title}
Description: {finding.description}
Suggested Fix: {finding.suggested_fix or '(none provided)'}
References: {', '.join(finding.references) if finding.references else '(none)'}
Confidence: {finding.confidence}

Generate a detailed educational explanation of this finding."""

        raw = self._call_llm(user_message, max_tokens=1500)
        parsed = self._parse_json(raw)

        return ExplainResult(
            finding_id=finding.id,
            finding=finding,
            what_is_this=parsed.get("what_is_this", ""),
            why_vulnerable=parsed.get("why_vulnerable", ""),
            how_to_fix=parsed.get("how_to_fix", ""),
            real_world_examples=parsed.get("real_world_examples", []),
            references=finding.references,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )


def save_last_result(result: CodeReviewResult) -> None:
    """
    Save the most recent review result to ~/.coderev/last_result.json.
    Called automatically at the end of every `coderev review` run.
    """
    LAST_RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAST_RESULT_PATH.write_text(result.model_dump_json(indent=2), encoding="utf-8")


def load_last_result() -> CodeReviewResult | None:
    """Load the most recent review result. Returns None if none exists."""
    if not LAST_RESULT_PATH.exists():
        return None
    try:
        return CodeReviewResult.model_validate_json(
            LAST_RESULT_PATH.read_text(encoding="utf-8")
        )
    except Exception:
        return None


def find_finding_by_id(result: CodeReviewResult, finding_id: str) -> Finding | None:
    """
    Find a finding by its ID prefix. Supports partial IDs (first 4+ chars).
    """
    finding_id = finding_id.lower().strip()
    # Exact match first
    for f in result.findings:
        if f.id == finding_id:
            return f
    # Prefix match
    matches = [f for f in result.findings if f.id.startswith(finding_id)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(
            f"Ambiguous ID '{finding_id}' matches {len(matches)} findings: "
            + ", ".join(f.id for f in matches)
            + "\nProvide more characters."
        )
    return None
