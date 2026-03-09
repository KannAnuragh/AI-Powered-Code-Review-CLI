"""CLI entry point for CodeRev.

All CLI commands are defined here using Typer.
Future commands (explain, config, etc.) will be added to this module.
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
        str,
        typer.Option(
            "--model",
            "-m",
            help="Model to use",
        ),
    ] = "moonshotai/kimi-k2-instruct",
    format: Annotated[
        str,
        typer.Option(
            "--format",
            help="Output format: rich, json, or markdown",
        ),
    ] = "rich",
    output: Annotated[
        Optional[Path],
        typer.Option(
            "--output",
            "-o",
            help="Save output to file",
        ),
    ] = None,
    fail_on: Annotated[
        str,
        typer.Option(
            "--fail-on",
            help="Exit with code 1 if severity found (critical, high, medium, low, info)",
        ),
    ] = "critical",
    min_confidence: Annotated[
        float,
        typer.Option(
            "--min-confidence",
            help="Filter out findings below this confidence threshold (0.0-1.0)",
            min=0.0,
            max=1.0,
        ),
    ] = 0.0,
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
    
    Examples:
        coderev review --diff changes.patch
        git diff | coderev review
        coderev review --diff changes.patch --format json --output results.json
    """
    # Validate format
    valid_formats = ["rich", "json", "markdown", "sarif"]
    if format not in valid_formats:
        console.print(f"[red]Error:[/red] Invalid format '{format}'. Use one of: {', '.join(valid_formats)}")
        raise typer.Exit(1)
    
    # Validate fail-on
    valid_severities = ["critical", "high", "medium", "low", "info"]
    if fail_on.lower() not in valid_severities:
        console.print(f"[red]Error:[/red] Invalid severity '{fail_on}'. Use one of: {', '.join(valid_severities)}")
        raise typer.Exit(1)
    
    # Get API key
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        console.print("[red]Error:[/red] GROQ_API_KEY environment variable not set.")
        console.print("Set it in your .env file or export it: export GROQ_API_KEY=your_key")
        raise typer.Exit(1)

    # Use env override for model if set
    model = os.getenv("CODEREV_MODEL", model)
    
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
    if format == "rich":
        console.print(f"[dim]Reviewing {len(file_paths)} file(s) with {model}...[/dim]")
    
    # Initialize pipeline and run review
    try:
        pipeline = ReviewPipeline(
            api_key=api_key,
            model=model,
            use_cache=not no_cache,
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
    if min_confidence > 0:
        original_count = len(result.findings)
        result.findings = [
            f for f in result.findings 
            if f.confidence >= min_confidence
        ]
        filtered_count = original_count - len(result.findings)
        if filtered_count > 0 and format == "rich":
            console.print(f"[dim]Filtered {filtered_count} low-confidence finding(s)[/dim]")
    
    # SARIF format handled separately — not part of the Formatter class
    if format == "sarif":
        from .sarif import sarif_to_string
        formatted_output = sarif_to_string(result)
        print(formatted_output)
        if output:
            output.write_text(formatted_output, encoding="utf-8")
            console.print(f"[dim]SARIF results saved to {output}[/dim]", stderr=True)
        exit_code = get_severity_exit_code(result.findings, fail_on)
        raise typer.Exit(exit_code)

    # Format output
    formatter = Formatter(console)
    formatted_output = formatter.format(
        result=result,
        format_type=format,
        input_tokens=input_tokens,
        output_tokens=output_tokens
    )
    
    # For json/markdown, print the output (plain print to avoid Rich markup)
    if format in ["json", "markdown"]:
        print(formatted_output)
    
    # Save to file if requested
    if output:
        try:
            if format == "rich":
                # For rich format, save as JSON when writing to file
                file_content = result.model_dump_json(indent=2)
            else:
                file_content = formatted_output
            
            output.write_text(file_content, encoding="utf-8")
            if format == "rich":
                console.print(f"[dim]Results saved to {output}[/dim]")
        except Exception as e:
            console.print(f"[red]Error saving output:[/red] {e}")
            raise typer.Exit(1)
    
    # Determine exit code
    exit_code = get_severity_exit_code(result.findings, fail_on)
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


# Entry point for direct execution
if __name__ == "__main__":
    app()
