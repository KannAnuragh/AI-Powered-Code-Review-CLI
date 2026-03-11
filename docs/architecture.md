# Architecture

## Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         CLI (cli.py)                            │
│  review · explain · config · eval · compare · badge · cache     │
└───────┬──────────────────────────┬──────────────────────────────┘
        │                          │
        ▼                          ▼
┌───────────────┐          ┌───────────────┐
│  Config Loader│          │  Explain Agent│
│  (config.py)  │          │  (explain.py) │
│               │          │               │
│ .coderev.toml │          │ ExplainResult │
│  ~/.coderev/  │          │ last_result   │
└───────────────┘          └───────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    Review Pipeline (pipeline.py)                 │
│                                                                  │
│  ┌──────────┐   ┌─────────────────────────┐   ┌──────────────┐ │
│  │ Chunker  │──▶│    Specialist Agents     │──▶│ Synthesizer  │ │
│  │chunker.py│   │  security.py             │   │synthesizer.py│ │
│  │          │   │  performance.py          │   │              │ │
│  │  Split   │   │  correctness (logic.py)  │   │  Dedup +     │ │
│  │  diff by │   │                          │   │  Rank +      │ │
│  │  file +  │   │  Each extends BaseAgent  │   │  Merge       │ │
│  │  function│   │  (agent.py)              │   │              │ │
│  └──────────┘   └─────────────────────────┘   └──────┬───────┘ │
│                                                       │         │
│  ┌──────────┐                                         │         │
│  │  Cache   │◀── SHA-256 keyed chunk cache ──────────▶│         │
│  │ cache.py │                                         │         │
│  └──────────┘                                         │         │
└───────────────────────────────────────────────────────┼─────────┘
                                                        │
                                                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Schema (schema.py)                            │
│                                                                  │
│  Finding · CodeReviewResult · ReviewMetadata                     │
│  Severity · Category · LineRange                                 │
│  EvalResult · EvalSummary · GoldenSample                        │
│  ReviewConfig · CodeRevConfig · ExplainResult                   │
└─────────────────────────────────────────────────────────────────┘
                        │
            ┌───────────┴───────────┐
            ▼                       ▼
    ┌──────────────┐        ┌──────────────┐
    │  Formatter   │        │    SARIF      │
    │formatter.py  │        │  sarif.py     │
    │              │        │              │
    │ Rich/JSON/   │        │ SARIF 2.1.0  │
    │ Markdown     │        │ for GitHub   │
    └──────────────┘        └──────────────┘
```

## Data Flow

### Review Flow

```
1. User runs:   coderev review --diff pr.patch
2. Config:      load_config() merges .coderev.toml + ~/.coderev/config.toml + defaults
3. CLI:         Reads diff content, extracts file paths
4. Pipeline:    ReviewPipeline.run(diff, file_paths)
   a. Chunker splits diff into file+function chunks
   b. Cache check — skip chunks with identical SHA-256
   c. Each chunk → security, performance, correctness agents (parallel)
   d. Synthesizer merges + deduplicates across agents
   e. Returns CodeReviewResult
5. Filter:      Remove findings below min_confidence
6. Persist:     save_last_result() → ~/.coderev/last_result.json
7. Format:      Formatter renders to requested format
8. Exit code:   Based on --fail-on severity threshold
```

### Explain Flow

```
1. User runs:   coderev explain a1b2c3d4
2. Load:        load_last_result() from ~/.coderev/last_result.json
3. Find:        find_finding_by_id() with prefix matching
4. Agent:       ExplainAgent.explain(finding) → LLM call
5. Display:     Rich Panel with educational explanation
```

### Eval Flow

```
1. User runs:   coderev eval
2. Load:        Golden samples from tests/golden/
3. Pipeline:    Run review on each sample (no cache)
4. Match:       Compare findings against expected per sample
5. Metrics:     Compute recall, precision, severity_accuracy, line_accuracy
6. Aggregate:   EvalSummary with pass/fail thresholds
7. Persist:     Append to results/eval_history.json
```

## Key Design Decisions

- **Pydantic v2 schema** — the `Finding` model is the stable contract. All
  agents output data validated against it. Breaking schema changes require a
  version bump.
- **BaseAgent pattern** — all agents extend `BaseAgent` which provides
  `_call_llm()` and `_parse_json()` with retry. Agent-specific logic lives
  in the system prompt and `review()` / `explain()` methods.
- **Config layering** — `.coderev.toml` is intentionally simple TOML. CLI
  flags override config; config overrides defaults. No environment variable
  config (except `GROQ_API_KEY` and `CODEREV_MODEL`).
- **Chunk caching** — SHA-256 of (system_prompt + user_message) avoids paying
  for identical LLM calls. Cache is disabled during eval for determinism.
