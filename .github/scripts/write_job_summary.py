#!/usr/bin/env python3
"""Write CodeRev review results to GitHub Actions job summary.

Usage:
    python write_job_summary.py review_result.json
"""

import json
import os
import sys


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: write_job_summary.py <result_file>", file=sys.stderr)
        sys.exit(1)

    try:
        with open(sys.argv[1]) as f:
            result = json.load(f)
    except Exception as e:
        print(f"Could not read result: {e}", file=sys.stderr)
        sys.exit(0)  # Don't fail the job over a summary write error

    findings = result.get("findings", [])
    counts = {
        s: sum(1 for f in findings if f["severity"] == s)
        for s in ["critical", "high", "medium", "low"]
    }

    summary = f"""## CodeRev AI Review Results

**Overall Risk:** {result.get('overall_risk', 'unknown').upper()}
**Total Findings:** {len(findings)}
**Tokens Used:** {result.get('metadata', {}).get('total_tokens', 0):,}
**Processing Time:** {result.get('metadata', {}).get('processing_time_seconds', 0)}s

| Critical | High | Medium | Low |
|----------|------|--------|-----|
| {counts['critical']} | {counts['high']} | {counts['medium']} | {counts['low']} |
"""

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a") as f:
            f.write(summary)
    else:
        # Not in GitHub Actions — print to stdout for local testing
        print(summary)


if __name__ == "__main__":
    main()
