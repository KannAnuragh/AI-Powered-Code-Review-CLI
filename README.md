
| `coderev compare` | A/B compare two models |
| `coderev badge --metric recall` | Generate shields.io quality badge |
| `coderev cache --stats` | Show prompt cache statistics |
| `coderev version` | Show version info |

### Review Options

```
-d, --diff PATH           Path to .patch / .diff file
-f, --files PATH          File list (one per line)
-m, --model TEXT          Groq model to use
    --format TEXT          Output: rich | json | markdown | sarif
-o, --output PATH         Write output to file
    --fail-on TEXT         Exit 1 at severity: critical|high|medium|low|info
    --min-confidence FLOAT Filter below threshold (0.0-1.0)
    --no-cache             Skip prompt cache
-c, --context TEXT         Extra context for the reviewer
```

### Explain

```bash
coderev explain a1b2c3d4           # full ID from review output
coderev explain a1b2               # prefix match (if unambiguous)
coderev explain a1b2 --from r.json # load from specific file
```

## How It Works

```
┌───────────┐     ┌──────────┐     ┌─────────────────────┐
│  git diff  │ ──▶ │ Chunker  │ ──▶ │  Multi-Agent Review │
└───────────┘     └──────────┘     │  ┌───────────────┐  │
                                    │  │  Security      │  │
                                    │  │  Performance   │  │
                                    │  │  Correctness   │  │
                                    │  └───────────────┘  │
                                    └──────────┬──────────┘
                                               │
                                    ┌──────────▼──────────┐
                                    │    Synthesizer      │
                                    │  Dedup + Rank       │
                                    └──────────┬──────────┘
                                               │
                                    ┌──────────▼──────────┐
                                    │   Formatter (Rich)  │
                                    │   JSON / Markdown   │
                                    │   SARIF             │
                                    └─────────────────────┘
```

1. **Chunker** — splits the diff by file + function, keeping chunks ≤ token limit
2. **Specialist agents** — each chunk goes to security, performance, and correctness agents
3. **Synthesizer** — deduplicates overlapping findings, assigns final severity + confidence
4. **Formatter** — outputs structured results in the requested format

## Quality Metrics

CodeRev ships a golden test suite of known-vulnerable code samples.
Run `coderev eval` to measure detection quality:

| Metric | Target | Description |
|--------|--------|-------------|
| Recall | ≥ 80% | Fraction of known vulnerabilities detected |
| Precision | ≥ 70% | Fraction of findings that are true positives |
| Severity accuracy | tracked | How often the severity matches expected |
| Line accuracy | tracked | How close line ranges are to expected |

Generate a quality badge: `coderev badge --format markdown`

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests (184 passing)
pytest tests/ --ignore=tests/test_agent.py -q

# Run with coverage
pytest --cov=coderev

# Type check
mypy coderev/
```

### Demo Files

The repo includes `sample_bad.py` (intentionally vulnerable code) and
`sample.patch` / `sample_new.patch` (pre-built diffs) for local testing:

```bash
coderev review --diff sample.patch
```

## Severity Levels

| Level | Emoji | Description |
|-------|-------|-------------|
| CRITICAL | 🔴 | Exploitable vulnerability, data loss, auth bypass |
| HIGH | 🟡 | Likely bug in production, significant degradation |
| MEDIUM | 🟠 | Possible issue under edge cases |
| LOW | 🔵 | Minor improvement opportunity |
| INFO | ⚪ | Style or best practice note |

