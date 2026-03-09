"""Tests for the multi-agent review pipeline.

Uses unittest.mock to patch agent calls — no real API calls.
"""

from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from coderev.chunker import DiffChunk
from coderev.pipeline import ReviewPipeline
from coderev.schema import CodeReviewResult


SECURITY_FINDINGS = [
    {
        "category": "security",
        "severity": "critical",
        "file_path": "app.py",
        "line_range": {"start": 10, "end": 12},
        "title": "SQL Injection in get_user",
        "description": "f-string in cursor.execute",
        "suggested_fix": 'cursor.execute("SELECT * FROM users WHERE id=?", (uid,))',
        "references": ["CWE-89"],
        "confidence": 0.95,
    }
]

LOGIC_FINDINGS = [
    {
        "category": "correctness",
        "severity": "high",
        "file_path": "app.py",
        "line_range": {"start": 30, "end": 32},
        "title": "Off-by-one in process_items loop",
        "description": "range(len(items)+1) causes IndexError",
        "suggested_fix": "for i in range(len(items)):",
        "references": [],
        "confidence": 1.0,
    }
]

PERF_FINDINGS = [
    {
        "category": "performance",
        "severity": "medium",
        "file_path": "app.py",
        "line_range": {"start": 50, "end": 55},
        "title": "N+1 query pattern",
        "description": "DB query inside loop",
        "suggested_fix": "Use batch fetch",
        "references": [],
        "confidence": 0.8,
    }
]

SAMPLE_DIFF = (
    "diff --git a/app.py b/app.py\n"
    "--- /dev/null\n"
    "+++ b/app.py\n"
    "@@ -0,0 +1,5 @@\n"
    "+def hello():\n"
    "+    return 1\n"
)


def _make_pipeline(**kwargs) -> ReviewPipeline:
    """Build a pipeline with mocked Groq clients."""
    with patch("coderev.agent.groq.Groq"):
        return ReviewPipeline(api_key="test-key", use_cache=False, **kwargs)


def _mock_agent_tokens(agent, inp=100, out=50):
    """Mock last_token_usage as a property instead of touching private attrs."""
    type(agent).last_token_usage = PropertyMock(return_value=(inp, out))


def _mock_synthesizer(pipeline, result=None):
    """Configure synthesizer with a mock result and token usage."""
    if result is None:
        result = MagicMock(spec=CodeReviewResult)
        result.metadata = MagicMock()
        result.metadata.total_tokens = 0
    pipeline.synthesizer.synthesize = MagicMock(return_value=result)
    _mock_agent_tokens(pipeline.synthesizer, 200, 100)
    return result


class TestPipelineCollectsFindings:
    def test_findings_from_all_agents(self):
        pipeline = _make_pipeline()

        pipeline.security.review = MagicMock(return_value=SECURITY_FINDINGS)
        pipeline.logic.review = MagicMock(return_value=LOGIC_FINDINGS)
        pipeline.performance.review = MagicMock(return_value=PERF_FINDINGS)
        _mock_agent_tokens(pipeline.security)
        _mock_agent_tokens(pipeline.logic)
        _mock_agent_tokens(pipeline.performance)
        _mock_synthesizer(pipeline)

        result = pipeline.run(SAMPLE_DIFF, ["app.py"])

        # Verify all three agents were called
        pipeline.security.review.assert_called_once()
        pipeline.logic.review.assert_called_once()
        pipeline.performance.review.assert_called_once()

        # Verify synthesizer received all findings via kwargs
        synth_call = pipeline.synthesizer.synthesize.call_args
        assert "all_findings" in synth_call.kwargs
        assert len(synth_call.kwargs["all_findings"]) == 3


class TestPipelineHandlesFailure:
    def test_agent_failure_does_not_kill_pipeline(self):
        pipeline = _make_pipeline()

        pipeline.security.review = MagicMock(side_effect=ValueError("boom"))
        pipeline.logic.review = MagicMock(return_value=LOGIC_FINDINGS)
        pipeline.performance.review = MagicMock(return_value=PERF_FINDINGS)
        _mock_agent_tokens(pipeline.logic)
        _mock_agent_tokens(pipeline.performance)
        _mock_synthesizer(pipeline)

        # Should not raise even though SecurityAgent failed
        result = pipeline.run(SAMPLE_DIFF, ["app.py"])

        # Synthesizer should have received findings from the 2 agents that succeeded
        synth_call = pipeline.synthesizer.synthesize.call_args
        assert "all_findings" in synth_call.kwargs
        assert len(synth_call.kwargs["all_findings"]) == 2


class TestPipelineCache:
    def test_cache_used_on_second_run(self):
        pipeline = _make_pipeline()
        pipeline.cache = MagicMock()
        pipeline.cache.get = MagicMock(return_value=None)  # first run: miss
        pipeline.cache.set = MagicMock()
        pipeline.cache.stats = {"hit_rate": 0.0, "entry_count": 0}

        pipeline.security.review = MagicMock(return_value=SECURITY_FINDINGS)
        pipeline.logic.review = MagicMock(return_value=LOGIC_FINDINGS)
        pipeline.performance.review = MagicMock(return_value=PERF_FINDINGS)
        _mock_agent_tokens(pipeline.security)
        _mock_agent_tokens(pipeline.logic)
        _mock_agent_tokens(pipeline.performance)
        _mock_synthesizer(pipeline)

        pipeline.run(SAMPLE_DIFF, ["app.py"])

        # cache.set should have been called 3 times (once per agent)
        assert pipeline.cache.set.call_count == 3

    def test_no_cache_flag_bypasses_cache(self):
        pipeline = _make_pipeline()
        assert pipeline.cache is None  # use_cache=False in _make_pipeline

        pipeline.security.review = MagicMock(return_value=[])
        pipeline.logic.review = MagicMock(return_value=[])
        pipeline.performance.review = MagicMock(return_value=[])
        _mock_agent_tokens(pipeline.security, 10, 5)
        _mock_agent_tokens(pipeline.logic, 10, 5)
        _mock_agent_tokens(pipeline.performance, 10, 5)
        _mock_synthesizer(pipeline)

        # Should work fine without cache
        result = pipeline.run(SAMPLE_DIFF, ["app.py"])
        assert result is not None


class TestPipelineMetadata:
    def test_metadata_has_correct_file_count(self):
        pipeline = _make_pipeline()

        pipeline.security.review = MagicMock(return_value=[])
        pipeline.logic.review = MagicMock(return_value=[])
        pipeline.performance.review = MagicMock(return_value=[])
        _mock_agent_tokens(pipeline.security, 10, 5)
        _mock_agent_tokens(pipeline.logic, 10, 5)
        _mock_agent_tokens(pipeline.performance, 10, 5)
        _mock_synthesizer(pipeline)

        pipeline.run(SAMPLE_DIFF, ["file1.py", "file2.py", "file3.py"])

        synth_call = pipeline.synthesizer.synthesize.call_args
        assert "metadata" in synth_call.kwargs
        assert synth_call.kwargs["metadata"].files_reviewed == 3


class TestPipelineCacheMetadata:
    def test_cache_stats_stored_in_metadata(self):
        """Cache hit rate should be in metadata, not the model string."""
        pipeline = _make_pipeline()
        pipeline.cache = MagicMock()
        pipeline.cache.get = MagicMock(return_value=None)
        pipeline.cache.set = MagicMock()
        pipeline.cache.stats = {"hit_rate": 0.33, "entry_count": 5}

        pipeline.security.review = MagicMock(return_value=[])
        pipeline.logic.review = MagicMock(return_value=[])
        pipeline.performance.review = MagicMock(return_value=[])
        _mock_agent_tokens(pipeline.security)
        _mock_agent_tokens(pipeline.logic)
        _mock_agent_tokens(pipeline.performance)

        mock_result = MagicMock(spec=CodeReviewResult)
        mock_result.metadata = MagicMock()
        mock_result.metadata.total_tokens = 0
        mock_result.metadata.model = "moonshotai/kimi-k2-instruct"
        mock_result.metadata.cache_hit_rate = 0.0
        mock_result.metadata.cache_entries_used = 0
        pipeline.synthesizer.synthesize = MagicMock(return_value=mock_result)
        _mock_agent_tokens(pipeline.synthesizer, 200, 100)

        result = pipeline.run(SAMPLE_DIFF, ["app.py"])

        # Model string must NOT contain cache info
        assert "cache" not in str(result.metadata.model)
        # Cache stats should be set on metadata fields
        assert result.metadata.cache_hit_rate == 0.33
        assert result.metadata.cache_entries_used == 5


class TestPipelineDeduplication:
    def test_duplicate_findings_both_passed_to_synthesizer(self):
        """Both SecurityAgent and LogicAgent flag the same issue.
        Pipeline passes both to synthesizer — dedup is the synthesizer's job."""
        duplicate_finding = {
            "category": "security",
            "severity": "critical",
            "file_path": "app.py",
            "line_range": {"start": 10, "end": 10},
            "title": "eval() with user input",
            "description": "Dangerous eval call",
            "suggested_fix": "Remove eval()",
            "references": ["CWE-94"],
            "confidence": 1.0,
        }
        pipeline = _make_pipeline()
        pipeline.security.review = MagicMock(return_value=[duplicate_finding])
        pipeline.logic.review = MagicMock(return_value=[duplicate_finding])
        pipeline.performance.review = MagicMock(return_value=[])
        _mock_agent_tokens(pipeline.security)
        _mock_agent_tokens(pipeline.logic)
        _mock_agent_tokens(pipeline.performance)
        _mock_synthesizer(pipeline)

        pipeline.run(SAMPLE_DIFF, ["app.py"])

        synth_call = pipeline.synthesizer.synthesize.call_args
        all_findings = synth_call.kwargs["all_findings"]
        assert len(all_findings) == 2  # pipeline passes both; synthesizer deduplicates


class TestPipelineChunkMerging:
    def test_findings_from_all_chunks_are_merged(self):
        """Multi-chunk diff: findings from ALL chunks reach the synthesizer."""
        pipeline = _make_pipeline()

        pipeline.security.review = MagicMock(return_value=[SECURITY_FINDINGS[0]])
        pipeline.logic.review = MagicMock(return_value=[LOGIC_FINDINGS[0]])
        pipeline.performance.review = MagicMock(return_value=[])
        _mock_agent_tokens(pipeline.security)
        _mock_agent_tokens(pipeline.logic)
        _mock_agent_tokens(pipeline.performance)
        _mock_synthesizer(pipeline)

        # Force 3 chunks
        mock_chunks = [
            DiffChunk("chunk1", ["a.py"], 0, 3, 0, 10),
            DiffChunk("chunk2", ["a.py"], 1, 3, 10, 20),
            DiffChunk("chunk3", ["a.py"], 2, 3, 20, 30),
        ]
        pipeline.chunker.chunk = MagicMock(return_value=mock_chunks)

        pipeline.run("fake diff", ["a.py"])

        # Each agent called once per chunk
        assert pipeline.security.review.call_count == 3
        assert pipeline.logic.review.call_count == 3

        # Synthesizer receives 3 chunks × 2 agents with findings = 6
        synth_call = pipeline.synthesizer.synthesize.call_args
        assert len(synth_call.kwargs["all_findings"]) == 6


class TestPipelineTokenAccumulation:
    def test_total_tokens_sum_all_agents(self):
        """total_tokens in metadata must be the sum of all agent calls."""
        pipeline = _make_pipeline()

        pipeline.security.review = MagicMock(return_value=SECURITY_FINDINGS)
        pipeline.logic.review = MagicMock(return_value=LOGIC_FINDINGS)
        pipeline.performance.review = MagicMock(return_value=PERF_FINDINGS)
        _mock_agent_tokens(pipeline.security, 1000, 500)    # 1500
        _mock_agent_tokens(pipeline.logic, 800, 400)         # 1200
        _mock_agent_tokens(pipeline.performance, 600, 300)   # 900

        mock_result = MagicMock(spec=CodeReviewResult)
        mock_result.metadata = MagicMock()
        mock_result.metadata.total_tokens = 0
        pipeline.synthesizer.synthesize = MagicMock(return_value=mock_result)
        _mock_agent_tokens(pipeline.synthesizer, 2000, 1000)  # 3000

        pipeline.run(SAMPLE_DIFF, ["app.py"])

        # Total: 1500 + 1200 + 900 + 3000 = 6600
        total = pipeline._total_input_tokens + pipeline._total_output_tokens
        assert total == 6600, f"Expected 6600 tokens, got {total}"
