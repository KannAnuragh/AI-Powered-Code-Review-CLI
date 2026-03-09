"""Groq AI agents for code review.

This module contains the intelligence layer — agents that send diffs
to Kimi K2 via Groq and receive structured code review feedback.

BaseAgent provides shared infrastructure (client, retries, JSON parsing).
CodeReviewAgent is the Week 1 general-purpose reviewer.
Week 2 adds SecurityAgent, LogicAgent, ArchitectureAgent, SynthesisAgent.
"""

import json
import time
from typing import Optional

import groq

from .schema import (
    Category,
    CodeReviewResult,
    Finding,
    ReviewMetadata,
    Severity,
)
from .utils import detect_languages_in_diff, count_diff_lines


# System prompt for the general-purpose code review agent
GENERAL_REVIEW_PROMPT = """You are an expert code reviewer running on Kimi K2.

PRIMARY TASK:
Review only the provided diff and return structured findings for:
security, performance, correctness, style, and test_coverage.

KIMI K2 OUTPUT PROTOCOL (strict):
1. Return a single JSON object only.
2. No markdown, no code fences, no commentary text.
3. Use double-quoted JSON keys/strings only.
4. If a field is unknown, omit it (do not invent values).
5. Do not include metadata; metadata is injected by the application.

EVIDENCE RULES:
- Report only issues that are directly supported by diff evidence.
- If line numbers are uncertain, omit line_range.
- Prefer fewer precise findings over many speculative findings.
- Consolidate duplicate findings on the same root issue.

SEVERITY:
- critical: clearly exploitable vuln, auth bypass, or data-loss risk
- high: likely production bug or major degradation
- medium: realistic edge-case issue
- low: minor improvement
- info: best-practice note

CONFIDENCE (0.0-1.0):
- 1.0 only when the issue is explicit in the diff.
- 0.7-0.9 for strong but context-dependent signals.
- 0.3-0.6 for weak evidence.

PRAISE:
- Include 0-3 specific praise items only when clearly earned.
- If none are credible, return an empty list.

TEST COVERAGE:
- If new non-trivial logic appears without visible tests in the diff,
  add a low-severity test_coverage finding with a concrete test suggestion.
"""


# ── Base Agent ────────────────────────────────────────────────────────


class BaseAgent:
    """Shared Groq client, retry logic, and response parsing.

    All specialized agents (security, logic, architecture, synthesis)
    inherit from this class and override the system prompt and/or schema.
    """

    SYSTEM_PROMPT: str = ""  # Must be overridden by subclass
    DEFAULT_MODEL: str = "moonshotai/kimi-k2-instruct"
    MAX_TOKENS = 4096

    def __init__(
        self,
        api_key: str,
        model: str = None,
        max_retries: int = 2,
    ):
        """Initialize the agent.

        Args:
            api_key: Groq API key
            model: Model to use (default: moonshotai/kimi-k2-instruct)
            max_retries: Number of retries for rate-limit errors
        """
        self.client = groq.Groq(api_key=api_key)
        self.model = model or self.DEFAULT_MODEL
        self.max_retries = max_retries
        self._last_input_tokens: int = 0
        self._last_output_tokens: int = 0

    def _call_llm(self, user_message: str, system_prompt: str = None, max_tokens: int = None) -> str:
        """Core LLM call with retry logic.

        Args:
            user_message: The user message containing the diff/task
            system_prompt: Override system prompt (defaults to self.SYSTEM_PROMPT)
            max_tokens: Override max tokens (defaults to self.MAX_TOKENS)

        Returns:
            Raw string response from the model.
        """
        prompt = system_prompt or self.SYSTEM_PROMPT
        tokens = max_tokens or self.MAX_TOKENS
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=tokens,
                    temperature=0.0,  # deterministic JSON output for Kimi K2
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": user_message},
                    ],
                )
                self._last_input_tokens = response.usage.prompt_tokens
                self._last_output_tokens = response.usage.completion_tokens
                return response.choices[0].message.content
            except groq.RateLimitError as e:
                last_error = e
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
                continue
            except groq.APIError:
                raise

        if last_error:
            raise last_error

    def _parse_json(self, raw: str) -> dict:
        """Strip markdown fences and parse JSON defensively.

        Raises ValueError with helpful message if parsing fails.
        """
        cleaned = (
            raw.strip()
            .removeprefix("```json")
            .removeprefix("```")
            .removesuffix("```")
            .strip()
        )
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Model returned invalid JSON. First 200 chars: {cleaned[:200]}"
            ) from e

    def review(self, diff: str, file_paths: list[str]) -> list[dict]:
        """Override in subclasses to return a list of raw finding dicts.

        The orchestrator collects these and merges them.
        """
        raise NotImplementedError

    @property
    def last_token_usage(self) -> tuple[int, int]:
        """Return (input_tokens, output_tokens) from the last API call."""
        return (self._last_input_tokens, self._last_output_tokens)


# ── General-purpose Code Review Agent ─────────────────────────────────


class CodeReviewAgent(BaseAgent):
    """General-purpose code review agent (Week 1).

    Sends the full diff in a single API call and returns a
    CodeReviewResult validated by Pydantic.
    """

    SYSTEM_PROMPT = GENERAL_REVIEW_PROMPT

    def review(
        self,
        diff: str,
        file_paths: list[str],
        additional_context: Optional[str] = None,
    ) -> CodeReviewResult:
        """Perform a code review on a git diff.

        Args:
            diff: The git diff content to review
            file_paths: List of file paths in the diff
            additional_context: Optional extra context for the review

        Returns:
            CodeReviewResult with findings, metadata, and praise

        Raises:
            groq.APIError: If the API call fails after retries
            pydantic.ValidationError: If the response doesn't match schema
        """
        start = time.time()

        schema_for_ai = self._get_response_schema()

        languages = detect_languages_in_diff(diff)
        lang_context = f"Languages detected: {', '.join(languages)}" if languages else ""

        user_message = self._build_user_message(
            diff=diff,
            file_paths=file_paths,
            schema=schema_for_ai,
            languages_context=lang_context,
            additional_context=additional_context,
        )

        raw = self._call_llm(user_message)
        elapsed = time.time() - start

        return self._parse_response(raw, diff, file_paths, elapsed)

    def _get_response_schema(self) -> dict:
        """JSON schema the AI must follow (metadata excluded)."""
        return {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "One-line verdict summarizing the review",
                },
                "overall_risk": {
                    "type": "string",
                    "enum": ["critical", "high", "medium", "low", "info"],
                    "description": "Overall risk level based on most severe finding",
                },
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "category": {
                                "type": "string",
                                "enum": [
                                    "security", "performance", "correctness",
                                    "style", "test_coverage",
                                ],
                            },
                            "severity": {
                                "type": "string",
                                "enum": ["critical", "high", "medium", "low", "info"],
                            },
                            "file_path": {"type": "string"},
                            "line_range": {
                                "type": "object",
                                "properties": {
                                    "start": {"type": "integer"},
                                    "end": {"type": "integer"},
                                },
                                "required": ["start", "end"],
                            },
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "suggested_fix": {"type": "string"},
                            "references": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "confidence": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                            },
                        },
                        "required": [
                            "category", "severity", "file_path",
                            "title", "description", "confidence",
                        ],
                    },
                },
                "praise": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "1-3 specific things done well",
                },
            },
            "required": ["summary", "overall_risk", "findings", "praise"],
        }

    def _build_user_message(
        self,
        diff: str,
        file_paths: list[str],
        schema: dict,
        languages_context: str,
        additional_context: Optional[str] = None,
    ) -> str:
        """Build the user message for the API call."""
        parts = [
            "Review this git diff:",
            "",
            f"Files changed: {', '.join(file_paths)}",
        ]

        if languages_context:
            parts.append(languages_context)

        if additional_context:
            parts.append(f"\nAdditional context: {additional_context}")

        parts.extend([
            "",
            "<diff>",
            diff,
            "</diff>",
            "",
            "Important: return only raw JSON matching the schema.",
            "Do not wrap in markdown fences and do not add prose.",
            "",
            "Respond with JSON matching this schema:",
            json.dumps(schema, indent=2),
        ])

        return "\n".join(parts)

    def _parse_response(
        self,
        raw: str,
        diff: str,
        file_paths: list[str],
        elapsed: float,
    ) -> CodeReviewResult:
        """Parse and validate the API response."""
        data = self._parse_json(raw)

        input_tokens, output_tokens = self.last_token_usage
        data["metadata"] = {
            "model": self.model,
            "total_tokens": input_tokens + output_tokens,
            "processing_time_seconds": round(elapsed, 2),
            "diff_lines": count_diff_lines(diff),
            "files_reviewed": len(file_paths),
        }

        return CodeReviewResult.model_validate(data)


# ── Exceptions ────────────────────────────────────────────────────────


class AgentError(Exception):
    """Base exception for agent errors."""
    pass


class SchemaValidationError(AgentError):
    """Raised when the model's response doesn't match the expected schema."""
    pass


class APIError(AgentError):
    """Raised when the Groq API returns an error."""
    pass
