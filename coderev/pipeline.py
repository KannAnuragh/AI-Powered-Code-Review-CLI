"""Multi-agent review pipeline.

Orchestrates chunking, specialist agents, caching, and synthesis
to produce a single CodeReviewResult.
"""

import time

from .agents import LogicAgent, PerformanceAgent, SecurityAgent, SynthesisAgent
from .cache import ChunkCache
from .chunker import ASTChunker
from .schema import CodeReviewResult, ReviewMetadata
from .utils import count_diff_lines


class ReviewPipeline:
    """Wire together chunker → specialist agents → synthesizer.

    Flow::

        diff → ASTChunker → chunks
        for each chunk:
            SecurityAgent    → security findings  (cached)
            LogicAgent       → logic findings      (cached)
            PerformanceAgent → perf findings       (cached)
        all findings → SynthesisAgent → CodeReviewResult
    """

    def __init__(
        self,
        api_key: str,
        model: str = "moonshotai/kimi-k2-instruct",
        use_cache: bool = True,
        cache_ttl_hours: int = 24,
    ):
        self.model = model
        self.security = SecurityAgent(api_key, model)
        self.logic = LogicAgent(api_key, model)
        self.performance = PerformanceAgent(api_key, model)
        self.synthesizer = SynthesisAgent(api_key, model)
        self.chunker = ASTChunker()
        self.cache = ChunkCache(ttl_hours=cache_ttl_hours) if use_cache else None

        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0

    def run(self, diff: str, file_paths: list[str]) -> CodeReviewResult:
        """Execute the full pipeline and return a validated result."""
        start_time = time.time()

        chunks = self.chunker.chunk(diff)
        all_findings: list[dict] = []

        for chunk in chunks:
            chunk_findings = self._review_chunk(chunk.content, chunk.file_paths)
            all_findings.extend(chunk_findings)

        elapsed = round(time.time() - start_time, 2)

        metadata = ReviewMetadata(
            model=self.model,
            total_tokens=self._total_input_tokens + self._total_output_tokens,
            processing_time_seconds=elapsed,
            diff_lines=count_diff_lines(diff),
            files_reviewed=len(set(file_paths)),
        )

        result = self.synthesizer.synthesize(
            all_findings=all_findings,
            diff=diff,
            file_paths=file_paths,
            metadata=metadata,
        )

        # Accumulate synthesizer tokens
        inp, out = self.synthesizer.last_token_usage
        self._total_input_tokens += inp
        self._total_output_tokens += out
        # Update metadata with final token count
        result.metadata.total_tokens = (
            self._total_input_tokens + self._total_output_tokens
        )

        if self.cache:
            stats = self.cache.stats
            result.metadata.cache_hit_rate = stats["hit_rate"]
            result.metadata.cache_entries_used = stats.get("entry_count", 0)

        return result

    @property
    def last_token_usage(self) -> tuple[int, int]:
        return (self._total_input_tokens, self._total_output_tokens)

    # ── internals ─────────────────────────────────────────────────────

    def _review_chunk(
        self, chunk_content: str, file_paths: list[str]
    ) -> list[dict]:
        """Run all three specialist agents on a single chunk."""
        findings: list[dict] = []

        agents = [
            (self.security, "SecurityAgent"),
            (self.logic, "LogicAgent"),
            (self.performance, "PerformanceAgent"),
        ]

        for agent, agent_name in agents:
            cached = None
            if self.cache:
                cached = self.cache.get(chunk_content, agent_name, self.model)

            if cached is not None:
                findings.extend(cached)
            else:
                try:
                    raw_findings = agent.review(chunk_content, file_paths)

                    # Accumulate tokens
                    inp, out = agent.last_token_usage
                    self._total_input_tokens += inp
                    self._total_output_tokens += out

                    if self.cache:
                        self.cache.set(
                            chunk_content, agent_name, self.model, raw_findings
                        )
                    findings.extend(raw_findings)
                except Exception as e:
                    import sys
                    print(
                        f"Warning: {agent_name} failed on chunk: {e}",
                        file=sys.stderr,
                    )

        return findings
