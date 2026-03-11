"""CLI entry point for CodeRev.

All CLI commands are defined here using Typer.
Commands: review, cache, eval, compare, config, explain, badge, version
"""

import os
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from dotenv import load_dotenv
from rich.console import Console

from . import __version__
from .formatter import Formatter
from .pipeline import ReviewPipeline
from .schema import Severity
from .utils import (
    extract_files_from_diff,
    get_severity_exit_code,
    read_diff_from_file,
    read_diff_from_stdin,
    read_files_list,
)

# Load environment variables from .env file
load_dotenv()

# Create the app
app = typer.Typer(
    name="coderev",
    help="AI-powered code review using Kimi K2",
    add_completion=False,
    no_args_is_help=True,
)

console = Console()


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        console.print(f"CodeRev version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        Optional[bool],
        typer.Option(
            "--version",
            "-v",
            help="Show version and exit",
            callback=version_callback,
            is_eager=True,
        ),
    ] = None,
) -> None:
    """CodeRev - AI-powered code review using Kimi K2."""
    pass


@app.command()
def review(
    diff: Annotated[
        Optional[Path],
        typer.Option(
            "--diff",
            "-d",
            help="Path to .patch or .diff file",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
    files: Annotated[
        Optional[Path],
        typer.Option(
            "--files",
            "-f",
            help="File containing list of changed files (one per line)",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ] = None,
    model: Annotated[
        Optional[str],
        typer.Option(
            "--model",
            "-m",
            help="Model to use",
        ),
    ] = None,
    format: Annotated[
        Optional[str],
        typer.Option(
            "--format",
            help="Output format: rich, json, markdown, sarif",
        ),
    ] = None,
    output: Annotated[
        Optional[Path],
        typer.Option(
            "--output",
            "-o",
            help="Save output to file",
        ),
    ] = None,
    fail_on: Annotated[
        Optional[str],
        typer.Option(
            "--fail-on",
            help="Exit with code 1 if severity found (critical, high, medium, low, info)",
        ),
    ] = None,
    min_confidence: Annotated[
        Optional[float],
        typer.Option(
            "--min-confidence",
            help="Filter out findings below this confidence threshold (0.0-1.0)",
            min=0.0,
            max=1.0,
        ),
    ] = None,
    no_cache: Annotated[
        bool,
        typer.Option(
            "--no-cache",
            help="Disable local chunk cache",
        ),
    ] = False,
    context: Annotated[
        Optional[str],
        typer.Option(
            "--context",
            "-c",
            help="Additional context to provide to the reviewer",
        ),
    ] = None,
) -> None:
    """Review a git diff using Kimi K2 AI.
    
    Reads diff from --diff file or stdin (e.g., git diff | coderev review).
    Defaults are read from .coderev.toml when CLI flags are not provided.
    
    Examples:
        coderev review --diff changes.patch
        git diff | coderev review
        coderev review --diff changes.patch --format json --output results.json
    """
    from .config import load_config

    # Load config for defaults
    try:
        cfg = load_config()
    except ValueError:
        cfg = None

    # Apply config defaults for unset flags
    effective_format = format or (cfg.review.format if cfg else "rich")
    effective_fail_on = fail_on or (
        cfg.review.fail_on.value if cfg and cfg.review.fail_on else "critical"
    )
    effective_min_confidence = (
        min_confidence if min_confidence is not None
        else (cfg.review.min_confidence if cfg else 0.0)
    )
    effective_model = model or (cfg.review.model if cfg else "moonshotai/kimi-k2-instruct")
    effective_no_cache = no_cache or (cfg.review.no_cache if cfg else False)

    # Validate format
    valid_formats = ["rich", "json", "markdown", "sarif"]
    if effective_format not in valid_formats:
        console.print(f"[red]Error:[/red] Invalid format '{effective_format}'. Use one of: {', '.join(valid_formats)}")
        raise typer.Exit(1)
    
    # Validate fail-on
    valid_severities = ["critical", "high", "medium", "low", "info"]
    if effective_fail_on.lower() not in valid_severities:
        console.print(f"[red]Error:[/red] Invalid severity '{effective_fail_on}'. Use one of: {', '.join(valid_severities)}")
        raise typer.Exit(1)
    
    # Get API key
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        console.print("[red]Error:[/red] GROQ_API_KEY environment variable not set.")
        console.print("Set it in your .env file or export it: export GROQ_API_KEY=your_key")
        raise typer.Exit(1)

    # Use env override for model if set
    effective_model = os.getenv("CODEREV_MODEL", effective_model)
    
    # Read diff content
    diff_content: Optional[str] = None
    
    if diff:
        try:
            diff_content = read_diff_from_file(diff)
        except Exception as e:
            console.print(f"[red]Error reading diff file:[/red] {e}")
            raise typer.Exit(1)
    else:
        # Try to read from stdin
        diff_content = read_diff_from_stdin()
        if not diff_content:
            console.print("[red]Error:[/red] No diff provided. Use --diff or pipe input via stdin.")
            console.print("Example: git diff | coderev review")
            raise typer.Exit(1)
    
    if not diff_content.strip():
        console.print("[yellow]Warning:[/yellow] Empty diff provided. Nothing to review.")
        raise typer.Exit(0)
    
    # Get file paths
    file_paths: list[str]
    if files:
        try:
            file_paths = read_files_list(files)
        except Exception as e:
            console.print(f"[red]Error reading files list:[/red] {e}")
            raise typer.Exit(1)
    else:
        # Extract from diff headers
        file_paths = extract_files_from_diff(diff_content)
    
    if not file_paths:
        console.print("[yellow]Warning:[/yellow] Could not extract file paths from diff.")
        file_paths = ["unknown"]
    
    # Show progress for rich format
    if effective_format == "rich":
        console.print(f"[dim]Reviewing {len(file_paths)} file(s) with {effective_model}...[/dim]")
    
    # Initialize pipeline and run review
    try:
        pipeline = ReviewPipeline(
            api_key=api_key,
            model=effective_model,
            use_cache=not effective_no_cache,
        )
        result = pipeline.run(
            diff=diff_content,
            file_paths=file_paths,
        )
        input_tokens, output_tokens = pipeline.last_token_usage
    except Exception as e:
        console.print(f"[red]Error during review:[/red] {e}")
        raise typer.Exit(1)
    
    # Filter findings by confidence
    if effective_min_confidence > 0:
        original_count = len(result.findings)
        result.findings = [
            f for f in result.findings 
            if f.confidence >= effective_min_confidence
        ]
        filtered_count = original_count - len(result.findings)
        if filtered_count > 0 and effective_format == "rich":
            console.print(f"[dim]Filtered {filtered_count} low-confidence finding(s)[/dim]")
    
    # Save result for coderev explain
    from .explain import save_last_result
    try:
        save_last_result(result)
    except Exception:
        pass  # non-critical — don't fail the review

    # SARIF format handled separately — not part of the Formatter class
    if effective_format == "sarif":
        from .sarif import sarif_to_string
        formatted_output = sarif_to_string(result)
        print(formatted_output)
        if output:
            output.write_text(formatted_output, encoding="utf-8")
            console.print(f"[dim]SARIF results saved to {output}[/dim]", stderr=True)
        exit_code = get_severity_exit_code(result.findings, effective_fail_on)
        raise typer.Exit(exit_code)

    # Format output
    formatter = Formatter(console)
    formatted_output = formatter.format(
        result=result,
        format_type=effective_format,
        input_tokens=input_tokens,
        output_tokens=output_tokens
    )
    
    # For json/markdown, print the output (plain print to avoid Rich markup)
    if effective_format in ["json", "markdown"]:
        print(formatted_output)
    
    # Save to file if requested
    if output:
        try:
            if effective_format == "rich":
                # For rich format, save as JSON when writing to file
                file_content = result.model_dump_json(indent=2)
            else:
                file_content = formatted_output
            
            output.write_text(file_content, encoding="utf-8")
            if effective_format == "rich":
                console.print(f"[dim]Results saved to {output}[/dim]")
        except Exception as e:
            console.print(f"[red]Error saving output:[/red] {e}")
            raise typer.Exit(1)
    
    # Determine exit code
    exit_code = get_severity_exit_code(result.findings, effective_fail_on)
    raise typer.Exit(exit_code)


@app.command()
def cache(
    clear: Annotated[
        bool,
        typer.Option("--clear", help="Clear all cached results"),
    ] = False,
    stats: Annotated[
        bool,
        typer.Option("--stats", help="Show cache statistics"),
    ] = False,
) -> None:
    """Manage the local chunk cache."""
    from .cache import ChunkCache

    c = ChunkCache()
    if clear:
        count = c.clear()
        console.print(f"Cleared {count} cached entries")
    if stats:
        s = c.stats
        console.print(
            f"Cache: {s['entry_count']} entries | "
            f"Hit rate: {s['hit_rate']:.0%} | "
            f"Dir: {s['cache_dir']}"
        )
    if not clear and not stats:
        console.print("Use --clear or --stats. See: coderev cache --help")


@app.command()
def version() -> None:
    """Show version information."""
    console.print(f"CodeRev version {__version__}")
    console.print("AI-powered code review using Groq (Kimi K2)")


@app.command(name="eval")
def eval_cmd(
    category: Annotated[
        Optional[str],
        typer.Option(
            "--category", "-c",
            help="Run only samples in this category: security|correctness|performance",
        ),
    ] = None,
    threshold: Annotated[
        float,
        typer.Option("--threshold", help="Recall threshold to pass (0.0-1.0)"),
    ] = 0.80,
    list_samples: Annotated[
        bool,
        typer.Option("--list", help="List available golden samples without running"),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose/--quiet"),
    ] = True,
    fail_on_regression: Annotated[
        bool,
        typer.Option("--fail/--no-fail", help="Exit code 1 if recall drops below threshold"),
    ] = True,
) -> None:
    """Run the evaluation suite against golden test samples.

    Measures recall, precision, severity accuracy, and line accuracy.
    Results are saved to results/eval_history.json.

    Examples:
        coderev eval                      # run all samples
        coderev eval --category security  # run only security samples
        coderev eval --list               # show available samples
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        console.print("[red]Error:[/red] GROQ_API_KEY not set", err=True)
        raise typer.Exit(1)

    from .eval import EvalRunner

    if list_samples:
        runner = EvalRunner(api_key=api_key)
        samples = runner._load_golden_samples()
        console.print(f"\nAvailable golden samples ({len(samples)} total):\n")
        for s in samples:
            fp_note = " [false positive check]" if s.false_positive_check else ""
            console.print(f"  {s.id}{fp_note}")
            console.print(f"    {s.description}")
            console.print(f"    Expected: {len(s.expected_findings)} finding(s)")
        return

    categories = [category] if category else None

    console.print(f"\n[bold]CodeRev Eval[/bold] — Running against golden samples\n")

    runner = EvalRunner(
        api_key=api_key,
        recall_threshold=threshold,
        precision_threshold=0.70,
    )

    try:
        summary = runner.run_all(categories=categories, verbose=verbose)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}", err=True)
        raise typer.Exit(1)

    console.print(f"\n{'─' * 60}")
    console.print(f"  Eval Summary — {summary.run_id}")
    console.print(f"{'─' * 60}")
    console.print(f"  Samples:    {summary.samples_passed}/{summary.total_samples} passed")
    console.print(f"  Recall:     {summary.avg_recall:.0%}  (threshold: {threshold:.0%})")
    console.print(f"  Precision:  {summary.avg_precision:.0%}")
    console.print(f"  Sev. Acc:   {summary.avg_severity_accuracy:.0%}")
    console.print(f"  Line Acc:   {summary.avg_line_accuracy:.0%}")
    console.print(f"  Cost:       ${summary.total_cost_usd:.4f} total")
    console.print(f"{'─' * 60}")

    if summary.samples_failed:
        console.print(f"\n  [red]Failed samples:[/red]")
        for sid in summary.samples_failed:
            console.print(f"     - {sid}")

    verdict = "[green]PASS[/green]" if summary.passed else "[red]FAIL[/red]"
    console.print(f"\n  {verdict}\n")
    console.print(f"  Results saved to: results/eval_history.json\n")

    if fail_on_regression and not summary.passed:
        raise typer.Exit(1)


@app.command()
def compare(
    diff: Annotated[
        Path,
        typer.Option("--diff", help="Diff file to compare reviews on", exists=True),
    ],
    runs: Annotated[
        int,
        typer.Option("--runs", help="Number of comparison runs (more = more reliable)"),
    ] = 3,
    output: Annotated[
        Optional[Path],
        typer.Option("--output", "-o", help="Save comparison result JSON to file"),
    ] = None,
) -> None:
    """Compare two review variants using LLM-as-judge.

    Runs the same diff through two variants of the pipeline and asks
    the judge which produces better findings.

    Examples:
        coderev compare --diff pr.patch --runs 5
    """
    import json as json_mod

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        console.print("[red]Error:[/red] GROQ_API_KEY not set", err=True)
        raise typer.Exit(1)

    diff_content = diff.read_text()

    console.print(f"\n[bold]CodeRev Compare[/bold] — LLM-as-Judge A/B Test\n")
    console.print(f"  Diff: {diff} ({len(diff_content.splitlines())} lines)")
    console.print(f"  Runs: {runs}\n")

    from .judge import LLMJudge

    pipeline_a = ReviewPipeline(api_key=api_key, use_cache=False)
    pipeline_b = ReviewPipeline(api_key=api_key, use_cache=False)

    reviews_a = []
    reviews_b = []

    for i in range(runs):
        console.print(f"  Run {i+1}/{runs}...", end="")
        ra = pipeline_a.run(diff_content, [str(diff)])
        rb = pipeline_b.run(diff_content, [str(diff)])
        reviews_a.append(ra.model_dump())
        reviews_b.append(rb.model_dump())
        console.print(" done")

    judge = LLMJudge(api_key=api_key)
    tournament = judge.run_tournament(
        diffs=[diff_content] * runs,
        reviews_a=reviews_a,
        reviews_b=reviews_b,
        label_a="Variant A (current)",
        label_b="Variant B (new)",
    )

    import re
    def _to_key(label: str) -> str:
        return re.sub(r'[^a-z0-9_]', '_', label.lower()).strip('_')

    key_a = _to_key("Variant A (current)")
    key_b = _to_key("Variant B (new)")

    console.print(f"\n  Results:")
    console.print(f"  Variant A wins: {tournament.get(f'{key_a}_wins', 0)}/{runs}")
    console.print(f"  Variant B wins: {tournament.get(f'{key_b}_wins', 0)}/{runs}")
    console.print(f"  Ties:           {tournament.get('ties', 0)}/{runs}")
    console.print(f"\n  Recommendation: {tournament.get('recommendation', '')}\n")

    if output:
        output.write_text(json_mod.dumps(tournament, indent=2))
        console.print(f"  Saved to: {output}\n")


@app.command()
def config(
    init: Annotated[
        bool,
        typer.Option(
            "--init",
            help="Create a .coderev.toml with commented defaults in the current directory",
        ),
    ] = False,
    validate: Annotated[
        bool,
        typer.Option(
            "--validate",
            help="Validate the current .coderev.toml and show parsed values",
        ),
    ] = False,
    show: Annotated[
        bool,
        typer.Option(
            "--show",
            help="Show the active config (merged from all sources)",
        ),
    ] = False,
) -> None:
    """Manage CodeRev configuration.

    Examples:
        coderev config --init       # create .coderev.toml with defaults
        coderev config --validate   # check your config file for errors
        coderev config --show       # show the active merged config
    """
    from .config import load_config, find_project_config, write_default_config

    if init:
        config_path = Path.cwd() / ".coderev.toml"
        if config_path.exists():
            typer.echo(f".coderev.toml already exists at {config_path}")
            raise typer.Exit(1)
        write_default_config(config_path)
        typer.echo(f"Created {config_path}")
        typer.echo("Edit it to customize your CodeRev settings.")
        return

    if validate:
        project_config = find_project_config()
        if not project_config:
            typer.echo("No .coderev.toml found in this directory or parents.")
            typer.echo("Run 'coderev config --init' to create one.")
            raise typer.Exit(1)
        try:
            cfg = load_config()
            typer.echo(f"{project_config} is valid")
            typer.echo(f"  fail_on:        {cfg.review.fail_on}")
            typer.echo(f"  min_confidence: {cfg.review.min_confidence}")
            typer.echo(f"  format:         {cfg.review.format}")
            typer.echo(f"  agents enabled: {cfg.agents.enabled}")
            if cfg.exclude.paths:
                typer.echo(f"  excluded paths: {cfg.exclude.paths}")
        except ValueError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)
        return

    if show:
        cfg = load_config()
        typer.echo("\nActive CodeRev config (merged from all sources):\n")
        typer.echo(f"  [review]")
        typer.echo(f"    fail_on:        {cfg.review.fail_on or 'none'}")
        typer.echo(f"    min_confidence: {cfg.review.min_confidence}")
        typer.echo(f"    format:         {cfg.review.format}")
        typer.echo(f"    model:          {cfg.review.model}")
        typer.echo(f"    no_cache:       {cfg.review.no_cache}")
        typer.echo(f"  [agents]")
        typer.echo(f"    enabled:        {cfg.agents.enabled}")
        typer.echo(f"  [exclude]")
        typer.echo(f"    paths:          {cfg.exclude.paths or '(none)'}")
        typer.echo(f"    categories:     {[c.value for c in cfg.exclude.categories] or '(none)'}")
        typer.echo(f"  [eval]")
        typer.echo(f"    recall_threshold:    {cfg.eval.recall_threshold}")
        typer.echo(f"    precision_threshold: {cfg.eval.precision_threshold}")
        return

    # Default: show help
    typer.echo("Use --init, --validate, or --show. See: coderev config --help")


@app.command()
def explain(
    finding_id: Annotated[
        str,
        typer.Argument(
            help="Finding ID to explain (full or prefix, e.g. 'a1b2c3d4' or 'a1b2')",
        ),
    ],
    result_file: Annotated[
        Optional[Path],
        typer.Option(
            "--from",
            help="Load findings from this JSON file instead of last review",
            exists=True,
        ),
    ] = None,
) -> None:
    """Get a detailed explanation of a code review finding.

    Finding IDs appear in square brackets in review output: [a1b2c3d4]
    Partial IDs work as long as they're unambiguous: coderev explain a1b2

    Examples:
        coderev explain a1b2c3d4
        coderev explain a1b2
        coderev explain a1b2c3d4 --from my_review.json
    """
    from .explain import ExplainAgent, load_last_result, find_finding_by_id
    from .schema import CodeReviewResult
    from rich.panel import Panel
    from rich import box

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        console.print("[red]Error:[/red] GROQ_API_KEY not set", err=True)
        raise typer.Exit(1)

    # Load result
    if result_file:
        try:
            result = CodeReviewResult.model_validate_json(result_file.read_text())
        except Exception as e:
            console.print(f"[red]Error:[/red] Could not load {result_file}: {e}", err=True)
            raise typer.Exit(1)
    else:
        result = load_last_result()
        if result is None:
            console.print(
                "[red]Error:[/red] No previous review found.\n"
                "   Run 'coderev review --diff <file>' first, then explain a finding.\n"
                "   Or use --from to specify a review JSON file.",
                err=True,
            )
            raise typer.Exit(1)

    # Find the finding
    try:
        finding = find_finding_by_id(result, finding_id)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}", err=True)
        raise typer.Exit(1)

    if finding is None:
        available = "\n".join(
            f"  [{f.id}] {f.title}" for f in result.findings
        )
        console.print(
            f"[red]Error:[/red] Finding '{finding_id}' not found in last review.\n\n"
            f"Available findings:\n{available}",
            err=True,
        )
        raise typer.Exit(1)

    # Generate explanation
    console.print(f"\n[dim]Generating explanation for [{finding.id}]...[/dim]")

    agent = ExplainAgent(api_key=api_key)
    explanation = agent.explain(finding)

    # Display
    severity_colors = {
        "critical": "bold red",
        "high": "bold orange1",
        "medium": "bold yellow",
        "low": "bold blue",
        "info": "dim",
    }
    sev_style = severity_colors.get(finding.severity.value, "white")
    location = f"{finding.file_path}"
    if finding.line_range:
        location += f":{finding.line_range.start}"

    header = (
        f"[bold]{finding.title}[/bold]\n"
        f"[dim]Category:[/dim] {finding.category.value}  "
        f"[dim]Severity:[/dim] [{sev_style}]{finding.severity.value.upper()}[/{sev_style}]  "
        f"[dim]Location:[/dim] {location}"
    )

    body_parts = [
        f"[bold cyan]WHAT IS THIS?[/bold cyan]\n{explanation.what_is_this}",
        f"[bold cyan]WHY IS THIS VULNERABLE?[/bold cyan]\n{explanation.why_vulnerable}",
        f"[bold cyan]HOW TO FIX IT[/bold cyan]\n{explanation.how_to_fix}",
    ]

    if explanation.real_world_examples:
        examples = "\n".join(f"  {ex}" for ex in explanation.real_world_examples)
        body_parts.append(f"[bold cyan]REAL WORLD IMPACT[/bold cyan]\n{examples}")

    if explanation.references:
        refs = "\n".join(f"  {ref}" for ref in explanation.references)
        body_parts.append(f"[bold cyan]REFERENCES[/bold cyan]\n{refs}")

    body = "\n\n".join(body_parts)

    console.print(Panel(
        f"{header}\n\n{body}",
        title=f"[bold]Finding [{finding.id}][/bold]",
        border_style=sev_style,
        box=box.ROUNDED,
        padding=(1, 2),
    ))
    console.print()


@app.command()
def badge(
    metric: Annotated[
        str,
        typer.Option(
            "--metric",
            help="Metric to show: recall | precision | tests",
        ),
    ] = "recall",
    output: Annotated[
        Optional[Path],
        typer.Option(
            "--output", "-o",
            help="Write badge URL to file",
        ),
    ] = None,
    format: Annotated[
        str,
        typer.Option(
            "--format",
            help="Output format: url | markdown | html",
        ),
    ] = "url",
) -> None:
    """Generate a shields.io quality badge from eval results.

    Reads results/eval_history.json and outputs a badge URL showing
    the latest recall score. Paste into README.md.

    Examples:
        coderev badge
        coderev badge --metric precision
        coderev badge --format markdown
    """
    import json as json_mod
    from urllib.parse import quote

    history_path = Path("results/eval_history.json")
    if not history_path.exists():
        typer.echo(
            "results/eval_history.json not found.\n"
            "Run 'coderev eval' first to generate quality metrics.",
            err=True,
        )
        raise typer.Exit(1)

    history = json_mod.loads(history_path.read_text())
    if not history:
        typer.echo("eval_history.json is empty. Run 'coderev eval' first.", err=True)
        raise typer.Exit(1)

    latest = history[-1]["summary"]

    if metric == "recall":
        value = f"{latest['avg_recall']:.0%}"
        label = "AI Recall"
        color = (
            "brightgreen" if latest["avg_recall"] >= 0.90
            else "green" if latest["avg_recall"] >= 0.80
            else "yellow" if latest["avg_recall"] >= 0.70
            else "red"
        )
    elif metric == "precision":
        value = f"{latest['avg_precision']:.0%}"
        label = "AI Precision"
        color = (
            "brightgreen" if latest["avg_precision"] >= 0.85
            else "green" if latest["avg_precision"] >= 0.70
            else "yellow" if latest["avg_precision"] >= 0.60
            else "red"
        )
    elif metric == "tests":
        import subprocess
        import re as re_mod
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "--ignore=tests/test_agent.py", "-q", "--tb=no"],
            capture_output=True, text=True,
        )
        match = re_mod.search(r"(\d+) passed", proc.stdout)
        count = match.group(1) if match else "?"
        value = f"{count} passing"
        label = "tests"
        color = "brightgreen"
    else:
        typer.echo(f"Unknown metric: {metric}. Use: recall | precision | tests", err=True)
        raise typer.Exit(1)

    # Build shields.io URL
    encoded_label = quote(label)
    encoded_value = quote(value)
    badge_url = f"https://img.shields.io/badge/{encoded_label}-{encoded_value}-{color}"

    if format == "markdown":
        output_str = f"![{label}]({badge_url})"
    elif format == "html":
        output_str = f'<img alt="{label}" src="{badge_url}">'
    else:
        output_str = badge_url

    typer.echo(output_str)

    if output:
        output.write_text(output_str, encoding="utf-8")
        typer.echo(f"\nSaved to: {output}", err=True)


# Entry point for direct execution
if __name__ == "__main__":
    app()
