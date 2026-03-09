"""Tests for the local chunk cache."""

import json
import time

import pytest

from coderev.cache import ChunkCache


@pytest.fixture
def cache(tmp_path):
    """Create a cache in a temp directory."""
    return ChunkCache(cache_dir=tmp_path, ttl_hours=24)


SAMPLE_FINDINGS = [
    {"category": "security", "severity": "high", "title": "SQL Injection"}
]


class TestCacheMiss:
    def test_miss_on_new_key(self, cache):
        result = cache.get("some content", "SecurityAgent", "model-x")
        assert result is None

    def test_miss_increments_counter(self, cache):
        cache.get("x", "A", "m")
        cache.get("y", "B", "m")
        assert cache.stats["misses"] == 2
        assert cache.stats["hits"] == 0


class TestCacheHit:
    def test_hit_after_set(self, cache):
        cache.set("chunk1", "SecurityAgent", "model-x", SAMPLE_FINDINGS)
        result = cache.get("chunk1", "SecurityAgent", "model-x")
        assert result == SAMPLE_FINDINGS

    def test_hit_increments_counter(self, cache):
        cache.set("chunk1", "SecurityAgent", "model-x", SAMPLE_FINDINGS)
        cache.get("chunk1", "SecurityAgent", "model-x")
        assert cache.stats["hits"] == 1
        assert cache.stats["misses"] == 0


class TestTTL:
    def test_expired_entry_returns_none(self, tmp_path):
        cache = ChunkCache(cache_dir=tmp_path, ttl_hours=0)  # 0-hour TTL
        cache.set("chunk", "Agent", "model", SAMPLE_FINDINGS)
        # TTL is 0 hours → immediate expiry
        time.sleep(0.05)
        result = cache.get("chunk", "Agent", "model")
        assert result is None


class TestKeyIsolation:
    def test_different_agents_have_separate_entries(self, cache):
        findings_a = [{"title": "finding from A"}]
        findings_b = [{"title": "finding from B"}]
        cache.set("same chunk", "SecurityAgent", "model", findings_a)
        cache.set("same chunk", "LogicAgent", "model", findings_b)

        assert cache.get("same chunk", "SecurityAgent", "model") == findings_a
        assert cache.get("same chunk", "LogicAgent", "model") == findings_b

    def test_different_models_have_separate_entries(self, cache):
        cache.set("chunk", "Agent", "model-a", [{"v": 1}])
        cache.set("chunk", "Agent", "model-b", [{"v": 2}])

        assert cache.get("chunk", "Agent", "model-a") == [{"v": 1}]
        assert cache.get("chunk", "Agent", "model-b") == [{"v": 2}]


class TestClear:
    def test_clear_removes_all(self, cache):
        cache.set("a", "A", "m", [])
        cache.set("b", "B", "m", [])
        cache.set("c", "C", "m", [])
        count = cache.clear()
        assert count == 3
        assert cache.stats["entry_count"] == 0

    def test_clear_empty_cache(self, cache):
        assert cache.clear() == 0


class TestStats:
    def test_hit_rate(self, cache):
        cache.set("chunk", "Agent", "m", [])
        cache.get("chunk", "Agent", "m")  # hit
        cache.get("other", "Agent", "m")  # miss
        cache.get("other2", "Agent", "m")  # miss
        stats = cache.stats
        assert stats["hits"] == 1
        assert stats["misses"] == 2
        assert abs(stats["hit_rate"] - 1 / 3) < 0.01

    def test_entry_count(self, cache):
        cache.set("a", "A", "m", [])
        cache.set("b", "B", "m", [])
        assert cache.stats["entry_count"] == 2


class TestCorruption:
    def test_corrupted_json_treated_as_miss(self, cache):
        # Write a corrupt file directly
        key = cache._key("content", "Agent", "model")
        path = cache._cache_path(key)
        path.write_text("NOT VALID JSON {{{", encoding="utf-8")

        result = cache.get("content", "Agent", "model")
        assert result is None
        # Corrupt file should be cleaned up
        assert not path.exists()

    def test_missing_fields_treated_as_miss(self, cache):
        key = cache._key("content", "Agent", "model")
        path = cache._cache_path(key)
        path.write_text(json.dumps({"wrong_key": "value"}), encoding="utf-8")

        result = cache.get("content", "Agent", "model")
        assert result is None
