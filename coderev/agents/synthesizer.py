"""SynthesisAgent — deduplicates and ranks findings from all specialist agents."""

import json
import uuid

from ..agent import BaseAgent
from ..schema import CodeReviewResult, ReviewMetadata


def _normalize_line_range(lr) -> dict | None:
    """Convert various line_range formats to ``{"start": int, "end": int}``."""
    if lr is None:
        return None
    if isinstance(lr, dict) and "start" in lr and "end" in lr:
        return lr
    if isinstance(lr, (list, tuple)) and len(lr) == 2:
        return {"start": int(lr[0]), "end": int(lr[1])}
    if isinstance(lr, str):
        # Handle "[11, 15]" string format
        lr = lr.strip().strip("[]")
        parts = [p.strip() for p in lr.split(",")]
        if len(parts) == 2:
            return {"start": int(parts[0]), "end": int(parts[1])}
    return None


class SynthesisAgent(BaseAgent):
    """Takes raw findings from all specialist agents and produces the final CodeReviewResult.

    Responsibilities:
    1. Deduplicate findings that overlap by (file_path, line_range)
    2. Resolve conflicting severity ratings (take the higher one with a note)
    3. Identify praise — things done well (requires seeing the full diff)
    4. Produce overall_risk and summary
    5. Validate and construct the final CodeReviewResult Pydantic object
    """

    SYSTEM_PROMPT = """You are the synthesis reviewer running on Kimi K2.

TASK:
Merge specialist findings (security, correctness, performance) into one final
review object.

KIMI K2 JSON RULES:
- Return exactly one JSON object.
- No markdown, no prose outside JSON.
- Keep keys exactly as required.

MERGE RULES:
1. Deduplicate same-issue findings at same file/line region.
2. If severities conflict, keep the higher severity.
3. Do not invent new findings that are absent from specialist inputs.
4. Preserve or lower confidence; do not inflate without stronger evidence.

OUTPUT RULES:
- summary: one sentence
- overall_risk: highest severity among final findings, else "info"
- praise: 0-3 specific and credible positives, else []

ANTI-PATTERNS:
- No generic praise.
- No silent dropping of valid findings.
- No severity downgrade without explicit rationale in description.
"""

    def synthesize(
        self,
        all_findings: list[dict],
        diff: str,
        file_paths: list[str],
        metadata: ReviewMetadata,
    ) -> CodeReviewResult:
        """Merge specialist findings into a final CodeReviewResult."""
        user_message = (
            "Here are findings from three specialist reviewers:\n\n"
            "<findings>\n"
            f"{json.dumps(all_findings, indent=2)}\n"
            "</findings>\n\n"
            "Here is the full diff for context (to identify praise):\n"
            f"<diff>\n{diff[:8000]}\n</diff>\n\n"
            f"Files reviewed: {', '.join(file_paths)}\n\n"
            "Synthesize these into a final JSON review object as described "
            "in your instructions."
        )

        raw = self._call_llm(user_message, max_tokens=6000)
        parsed = self._parse_json(raw)

        # Add generated IDs to findings that don't have them
        for f in parsed.get("findings", []):
            if "id" not in f or not f["id"]:
                f["id"] = str(uuid.uuid4())[:8]
            # Normalize line_range — model sometimes returns arrays or strings
            lr = f.get("line_range")
            if lr is not None:
                f["line_range"] = _normalize_line_range(lr)

        # Inject metadata
        parsed["metadata"] = metadata.model_dump()

        return CodeReviewResult.model_validate(parsed)
