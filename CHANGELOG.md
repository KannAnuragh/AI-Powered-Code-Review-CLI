# Changelog

All notable changes to CodeRev are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/).

## [0.5.0] — 2025-07-18

### Added
- **`.coderev.toml` config system** — project-level and user-level config with
  priority merging. CLI flags always win. `coderev config --init` to bootstrap.
- **`coderev explain <id>`** — deep-dive educational explanation of any finding,
  powered by the ExplainAgent. Supports partial ID prefix matching.
- **`coderev badge`** — generate shields.io quality badges from eval results
  (recall, precision, or test count).
- **Config models** — `ReviewConfig`, `AgentsConfig`, `ExcludeConfig`,
  `EvalConfig`, `CodeRevConfig` in `schema.py`.
- **`ExplainResult` model** — structured output from the explain agent.
- **Last-result persistence** — review results automatically saved to
  `~/.coderev/last_result.json` for use by `explain`.
- **README overhaul** — badges, architecture diagram, full command reference,
  configuration guide, quality metrics table.
- **`docs/architecture.md`** — component diagram and data flow documentation.
- **`.coderev.toml.example`** — committed example config for new users.
- 42 new tests (184 total, 0 failures).

### Changed
- `review` command now reads defaults from `.coderev.toml` when CLI flags are
  not provided. Parameters changed from hard defaults to `Optional` types.
- CLI `--format` now also accepts `sarif` in help text.

## [0.4.0] — 2025-07-11

### Added
- **Golden test suite** — 6 curated samples across security, performance,
  correctness, and clean-code categories.
- **`coderev eval`** — automated evaluation pipeline measuring recall,
  precision, severity accuracy, and line accuracy against golden samples.
- **`coderev compare`** — A/B tournament comparison between two models.
- **`EvalResult` / `EvalSummary` models** — structured eval output with
  `passed` computed field.
- **Eval history** — results appended to `results/eval_history.json`.
- `test_eval.py`, `test_judge.py` — 40+ eval-specific tests.

### Changed
- `EvalRunner.use_cache` hardcoded to `False` for deterministic eval runs.
- Tournament dict keys normalized (no spaces/parens).

## [0.3.0] — 2025-07-04

### Added
- **SARIF output** — `--format sarif` produces SARIF 2.1.0 for GitHub Code
  Scanning integration.
- **GitHub Actions workflows** — `review.yml`, `eval.yml`, `test.yml`, `pr-comment.yml`.
- `coderev cache --stats / --clear` — manage prompt-level chunk cache.
- `sample.patch` and `sample_new.patch` for local testing.
- `test_sarif.py` — SARIF schema validation tests.

## [0.2.0] — 2025-06-27

### Added
- **Multi-agent pipeline** — security, performance, and correctness specialist
  agents with a synthesiser for dedup and ranking.
- **AST-aware chunker** — splits diffs by file + function boundary, respects
  token limits.
- **Prompt-level chunk caching** — SHA-256 keyed cache avoids re-reviewing
  identical chunks.
- `coderev version` command.
- `test_chunker.py`, `test_pipeline.py`, `test_cache.py`.

## [0.1.0] — 2025-06-20

### Added
- Initial release: single-agent review with Groq (Kimi K2).
- Rich terminal output with severity colours and emoji.
- JSON and Markdown output formats.
- `--fail-on` exit codes for CI/CD gating.
- Pydantic v2 schema (`Finding`, `CodeReviewResult`, `ReviewMetadata`).
- `test_schema.py`, `test_utils.py`.
