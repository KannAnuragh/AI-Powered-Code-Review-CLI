# CodeRev

**AI-powered code review CLI using Groq Kimi K2**

CodeRev analyzes git diffs and returns structured, actionable code review feedback with severity ratings, fix suggestions, and references to security standards.

## Features

- 🔍 **Intelligent Code Review** - Analyzes diffs for security vulnerabilities, logic errors, performance issues, and more
- 📊 **Structured Output** - Returns findings with severity, category, line numbers, and confidence scores
- 💡 **Fix Suggestions** - Provides actual code snippets to fix issues, not just descriptions
- 🎨 **Beautiful Terminal Output** - Rich, colorful, scannable output using the Rich library
- 📝 **Multiple Formats** - Output as rich terminal, JSON, or Markdown
- 🔗 **References** - Links to CWE IDs, OWASP categories, and language-specific documentation
- ✨ **Balanced Feedback** - Includes praise for things done well, not just criticism
- 🚀 **CI-Ready** - Exit codes for CI/CD integration

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/your-username/coderev.git
cd coderev

# Install in development mode
pip install -e .

# Or install dependencies directly
pip install -e ".[dev]"
```

### Configuration

Create a `.env` file with your Groq API key:

```bash
cp .env.example .env
# Edit .env and add your API key
```

Or set the environment variable directly:

```bash
export GROQ_API_KEY=your_api_key_here
```

### Usage

**Review a diff file:**

```bash
coderev review --diff changes.patch
```

**Pipe from git:**

```bash
git diff | coderev review
git diff HEAD~1 | coderev review
```

**Output as JSON:**

```bash
coderev review --diff changes.patch --format json
```

**Save output to file:**

```bash
coderev review --diff changes.patch --output results.json
```

**Filter low-confidence findings:**

```bash
coderev review --diff changes.patch --min-confidence 0.8
```

**Fail on high severity (for CI):**

```bash
coderev review --diff changes.patch --fail-on high
```

## CLI Options

```
Usage: coderev review [OPTIONS]

Options:
  -d, --diff PATH           Path to .patch or .diff file
  -f, --files PATH          File containing list of changed files
  -m, --model TEXT          Model to use [default: kimi-k2-0528]
  --format TEXT             Output format: rich, json, markdown [default: rich]
  -o, --output PATH         Save output to file
  --fail-on TEXT            Exit with code 1 if severity found [default: critical]
  --min-confidence FLOAT    Filter findings below threshold [default: 0.0]
  -c, --context TEXT        Additional context for the reviewer
  --help                    Show this message and exit
```

## Example Output

```
┌─────────────────────────────────────────────────────┐
│  CodeRev  •  kimi-k2-0528  •  12.4s                 │
│  3 files reviewed  •  1,847 diff lines              │
└─────────────────────────────────────────────────────┘

📁 src/auth/login.py
  🔴 CRITICAL  [sec] SQL Injection                     L:47–52
     User input concatenated directly into raw SQL query.
     Fix: cursor.execute("SELECT * FROM users WHERE id=?", (user_id,))
     → CWE-89 · OWASP A03:2021  [conf: 0.97]

✨ What's done well:
   • Input validation on registration form (login.py L:12–18)
   • Clear separation of DB and business logic

──────────────────────────────────────────────────────
  Risk: HIGH  |  1 critical · 1 high · 1 medium
  Score: 42/100  ⚠  Findings require attention
  Tokens: 18,432  (~$0.023)  |  Time: 12.4s
```

## Severity Levels

| Level    | Emoji | Description |
|----------|-------|-------------|
| CRITICAL | 🔴    | Exploitable vulnerability, data loss risk, auth bypass |
| HIGH     | 🟡    | Likely bug in production, significant degradation |
| MEDIUM   | 🟠    | Possible issue under edge cases |
| LOW      | 🔵    | Minor improvement opportunity |
| INFO     | ⚪    | Style or best practice note |

## Categories

- **security** - Security vulnerabilities (SQL injection, XSS, etc.)
- **performance** - Performance issues (N+1 queries, memory leaks)
- **correctness** - Logic errors, bugs, edge cases
- **style** - Code style, naming, documentation
- **test_coverage** - Missing tests, untested edge cases

## Testing

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run with coverage
pytest --cov=coderev
```

### Testing with Sample Bad Code

The repository includes `sample_bad.py` with intentional vulnerabilities for testing:

```bash
# Generate a diff
git add sample_bad.py
git diff --cached > sample.patch

# Review it
coderev review --diff sample.patch
```

## Project Structure

```
coderev/
├── coderev/
│   ├── __init__.py       # Package initialization
│   ├── cli.py            # CLI entry point
│   ├── schema.py         # Pydantic models
│   ├── agent.py          # Claude agent
│   ├── formatter.py      # Rich output formatter
│   └── utils.py          # Helper utilities
├── tests/
│   ├── test_schema.py    # Schema tests
│   └── test_utils.py     # Utils tests
├── pyproject.toml        # Package configuration
├── README.md             # This file
├── .env.example          # Environment template
└── sample_bad.py         # Test file with issues
```

## Roadmap

- **Week 1** ✅ Core CLI with Claude integration
- **Week 2** Multi-agent pipeline, AST chunker, prompt caching
- **Week 3** GitHub Actions workflow, SARIF output, PR comments
- **Week 4** Golden test suite, eval runner, A/B testing
- **Week 5** Open-source polish, config system, `coderev explain`

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions welcome! Please read CONTRIBUTING.md for guidelines.
