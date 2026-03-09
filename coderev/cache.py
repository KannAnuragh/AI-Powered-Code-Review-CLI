"""Local file-based chunk cache.

Keyed by SHA-256(chunk_content + agent_name + model_name).
Stores results at ~/.coderev/cache/ with a configurable TTL.
"""

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path


class ChunkCache:
    """Cache AI review results locally so unchanged chunks are free on re-run.

    Location: ``~/.coderev/cache/``
    Default TTL: 24 hours
    """

    DEFAULT_CACHE_DIR = Path.home() / ".coderev" / "cache"
    DEFAULT_TTL_HOURS = 24

    def __init__(
        self,
        cache_dir: Path | None = None,
        ttl_hours: int = DEFAULT_TTL_HOURS,
    ):
        self.cache_dir = cache_dir or self.DEFAULT_CACHE_DIR
        self.ttl = timedelta(hours=ttl_hours)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._hits = 0
        self._misses = 0

    # ── public API ────────────────────────────────────────────────────

    def get(
        self, chunk_content: str, agent_name: str, model: str
    ) -> list[dict] | None:
        """Return cached findings if available and fresh, else ``None``."""
        path = self._cache_path(self._key(chunk_content, agent_name, model))

        if not path.exists():
            self._misses += 1
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            cached_at = datetime.fromisoformat(data["cached_at"])

            if datetime.now() - cached_at > self.ttl:
                path.unlink()
                self._misses += 1
                return None

            self._hits += 1
            return data["findings"]
        except (json.JSONDecodeError, KeyError, ValueError):
            path.unlink(missing_ok=True)
            self._misses += 1
            return None

    def set(
        self,
        chunk_content: str,
        agent_name: str,
        model: str,
        findings: list[dict],
    ) -> None:
        """Store *findings* in the cache."""
        path = self._cache_path(self._key(chunk_content, agent_name, model))
        data = {
            "cached_at": datetime.now().isoformat(),
            "agent": agent_name,
            "model": model,
            "findings": findings,
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def clear(self) -> int:
        """Delete all cache entries. Returns count deleted."""
        count = 0
        for f in self.cache_dir.glob("*.json"):
            f.unlink()
            count += 1
        return count

    @property
    def stats(self) -> dict:
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / max(1, self._hits + self._misses),
            "cache_dir": str(self.cache_dir),
            "entry_count": len(list(self.cache_dir.glob("*.json"))),
        }

    # ── internals ─────────────────────────────────────────────────────

    def _key(self, chunk_content: str, agent_name: str, model: str) -> str:
        raw = f"{agent_name}:{model}:{chunk_content}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"
