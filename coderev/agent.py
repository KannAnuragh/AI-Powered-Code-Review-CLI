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
SYSTEM_PROMPT = """You are a senior software engineer performing a focused code review.

ROLE:
Review the provided git diff for security vulnerabilities, logic errors, 
performance issues, missing error handling, and test coverage gaps.

CONSTRAINTS:
- Only report findings you can trace to specific lines in the diff
- Severity must be calibrated to actual exploitability and impact:
    critical = exploitable, data loss risk, or auth bypass possible
    high     = likely bug in production, significant degradation
    medium   = possible issue under edge cases
    low      = minor improvement opportunity
    info     = style or best practice note only
- Never hallucinate line numbers. If uncertain, omit line_range entirely.
- Include suggested_fix as a real code snippet when possible, not just prose.
- Confidence must reflect how certain you are (0.0–1.0).
- Add references to CWE IDs, OWASP categories, or language-specific docs when relevant.
- Include 1–3 items in praise[] for things done well. Be specific, not generic.

OUTPUT CONTRACT:
Respond ONLY with valid JSON matching the schema provided.
No preamble, no explanation, no markdown fences. Raw JSON only.

ANTI-PATTERNS TO AVOID:
- Do not flag commented-out code unless it contains active secrets
- Do not report "could potentially" findings without concrete diff evidence
- Do not repeat the same finding for multiple similar lines — consolidate
- Do not use vague titles like "Bad Code". Be precise: "Unsanitized user input in SQL query"
- Do not include the metadata field in your response - it will be added programmatically"""


# ── Base Agent ────────────────────────────────────────────────────────


class BaseAgent:
    """Shared Groq client, retry logic, and response parsing.

    All specialized agents (security, logic, architecture, synthesis)
    inherit from this class and override the system prompt and/or schema.
    """

    DEFAULT_MODEL = "kimi-k2-0528"
    MAX_TOKENS = 4096

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        max_retries: int = 2,
    ):
        """Initialize the agent.

        Args:
            api_key: Groq API key
            model: Model to use (default: kimi-k2-0528)
            max_retries: Number of retries for rate-limit errors
        """
        self.client = groq.Groq(api_key=api_key)
        self.model = model
        self.max_retries = max_retries
        self._last_input_tokens: int = 0
        self._last_output_tokens: int = 0

    def _call_api(self, system_prompt: str, user_message: str):
        """Make a chat completion call to Groq with retry logic.

        Args:
            system_prompt: The system prompt for this agent
            user_message: The user message containing the diff/task
        """
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=self.MAX_TOKENS,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                )
                return response
            except groq.RateLimitError as e:
                last_error = e
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
                continue
            except groq.APIError:
                raise

        if last_error:
            raise last_error

    @staticmethod
    def _clean_json_response(raw: str) -> str:
        """Strip markdown fences to extract pure JSON."""
        raw = raw.strip()
        if raw.startswith("```json"):
            raw = raw[7:]
        elif raw.startswith("```"):
            raw = raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        return raw.strip()

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

        response = self._call_api(SYSTEM_PROMPT, user_message)
        elapsed = time.time() - start

        return self._parse_response(response, diff, file_paths, elapsed)

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
            "Respond with JSON matching this schema:",
            json.dumps(schema, indent=2),
        ])

        return "\n".join(parts)

    def _parse_response(
        self,
        response,
        diff: str,
        file_paths: list[str],
        elapsed: float,
    ) -> CodeReviewResult:
        """Parse and validate the API response."""
        raw = response.choices[0].message.content
        raw = self._clean_json_response(raw)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Kimi K2 returned invalid JSON: {e}\nRaw response: {raw[:500]}"
            )

        data["metadata"] = {
            "model": self.model,
            "total_tokens": response.usage.prompt_tokens + response.usage.completion_tokens,
            "processing_time_seconds": round(elapsed, 2),
            "diff_lines": count_diff_lines(diff),
            "files_reviewed": len(file_paths),
        }

        self._last_input_tokens = response.usage.prompt_tokens
        self._last_output_tokens = response.usage.completion_tokens

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
