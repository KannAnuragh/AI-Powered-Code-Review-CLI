# CodeRev

![AI Recall](https://img.shields.io/badge/AI%20Recall-≥80%25-green)
![Tests](https://img.shields.io/badge/tests-184%20passing-brightgreen)
![Python](https://img.shields.io/badge/python-≥3.11-blue)
![License](https://img.shields.io/badge/license-MIT-green)

**AI-powered code review CLI** — finds security vulnerabilities, logic errors,
and performance issues in your diffs using Groq (Kimi K2). Returns structured,
actionable findings with severity ratings, fix suggestions, and CWE/OWASP
references.

---

## What It Does

CodeRev reads a git diff, splits it into semantic chunks, sends each chunk
through specialised AI agents (security, performance, correctness), synthesises
the results, and outputs structured findings. Use it locally or in CI — the
exit code reflects the worst severity found.

**Key capabilities:**

- Multi-agent review pipeline (security · performance · correctness)
- Structured output with severity, category, line numbers, confidence scores
- Copy-pasteable fix suggestions with CWE / OWASP references
- Rich terminal, JSON, Markdown, and SARIF output formats
- Prompt-level chunk caching for faster re-reviews
- Golden test suite with measurable recall & precision
- CI-ready exit codes and GitHub Actions integration
- `coderev explain <id>` for deep-dive vulnerability education

## Quick Start

```bash
# Clone and install
git clone https://github.com/KannAnuragh/AI-Powered-Code-Review-CLI.git
cd AI-Powered-Code-Review-CLI/coderev
pip install -e ".[dev]"

# Set your Groq API key
cp .env.example .env          # then edit .env
# or: export GROQ_API_KEY=your_key

# Review a diff
git diff | coderev review
coderev review --diff changes.patch
coderev review --diff changes.patch --format json --output results.json
```

## GitHub Actions

Add CodeRev to your CI pipeline:

```yaml
name: Code Review
on: [pull_request]

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install -e .
      - run: |
          git diff origin/main...HEAD > pr.patch
          coderev review --diff pr.patch --format sarif --output results.sarif --fail-on high
        env:
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
      - uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: results.sarif
```

## Configuration

CodeRev reads settings from `.coderev.toml` in your project root. CLI flags
always take precedence.

```bash
coderev config --init       # create .coderev.toml with defaults
coderev config --validate   # check your config for errors
coderev config --show       # show effective merged config
```

Example `.coderev.toml`:

```toml
[review]
fail_on = "high"
min_confidence = 0.7
format = "rich"

[agents]
enabled = ["security", "performance", "correctness"]

[exclude]
paths = ["vendor/", "generated/"]

[eval]
recall_threshold = 0.80
precision_threshold = 0.70
```

Config priority: CLI flags > `.coderev.toml` (project) > `~/.coderev/config.toml` (user) > built-in defaults.

## Commands

| Command | Description |
|---------|-------------|
| `coderev review --diff <file>` | Review a diff file or stdin |
| `coderev explain <id>` | Deep-dive explanation of a finding |
| `coderev config --init` | Create `.coderev.toml` with defaults |
| `coderev eval` | Run golden test suite |
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

