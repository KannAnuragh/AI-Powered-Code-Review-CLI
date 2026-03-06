"""Rich terminal output formatter for code review results.

This module handles the UX layer - rendering beautiful, scannable output
in the terminal using the Rich library.
"""

import json
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from .schema import (
    Category,
    CodeReviewResult,
    Finding,
    Severity,
)
from .utils import estimate_cost, format_cost


# Severity emoji mapping
SEVERITY_EMOJI = {
    Severity.CRITICAL: "🔴",
    Severity.HIGH: "🟡",
    Severity.MEDIUM: "🟠",
    Severity.LOW: "🔵",
    Severity.INFO: "⚪",
}

# Severity color mapping for Rich
SEVERITY_COLORS = {
    Severity.CRITICAL: "red bold",
    Severity.HIGH: "yellow bold",
    Severity.MEDIUM: "dark_orange",
    Severity.LOW: "blue",
    Severity.INFO: "dim",
}

# Category abbreviations
CATEGORY_ABBREV = {
    Category.SECURITY: "sec",
    Category.PERFORMANCE: "perf",
    Category.CORRECTNESS: "corr",
    Category.STYLE: "style",
    Category.TEST_COVERAGE: "test",
}


class Formatter:
    """Formatter for code review output.
    
    Supports multiple output formats: rich (terminal), JSON, and markdown.
    """
    
    def __init__(self, console: Optional[Console] = None):
        """Initialize the formatter.
        
        Args:
            console: Rich Console instance (creates new one if not provided)
        """
        self.console = console or Console()
    
    def format(
        self,
        result: CodeReviewResult,
        format_type: str = "rich",
        input_tokens: int = 0,
        output_tokens: int = 0
    ) -> str:
        """Format a code review result.
        
        Args:
            result: The CodeReviewResult to format
            format_type: Output format ('rich', 'json', 'markdown')
            input_tokens: Input token count for cost calculation
            output_tokens: Output token count for cost calculation
            
        Returns:
            Formatted string (for json/markdown) or empty string (for rich, prints directly)
        """
        if format_type == "json":
            return self._format_json(result)
        elif format_type == "markdown":
            return self._format_markdown(result, input_tokens, output_tokens)
        else:
            self._format_rich(result, input_tokens, output_tokens)
            return ""
    
    def _format_rich(
        self,
        result: CodeReviewResult,
        input_tokens: int,
        output_tokens: int
    ) -> None:
        """Render rich terminal output."""
        # Header panel
        self._render_header(result)
        
        # Findings grouped by file
        self._render_findings(result)
        
        # Praise section
        self._render_praise(result)
        
        # Footer with summary
        self._render_footer(result, input_tokens, output_tokens)
    
    def _render_header(self, result: CodeReviewResult) -> None:
        """Render the header panel."""
        meta = result.metadata
        
        header_text = Text()
        header_text.append("  CodeRev  ", style="bold cyan")
        header_text.append("•  ", style="dim")
        header_text.append(meta.model, style="dim")
        header_text.append("  •  ", style="dim")
        header_text.append(f"{meta.processing_time_seconds}s", style="dim")
        header_text.append("\n")
        header_text.append(f"  {meta.files_reviewed} files reviewed", style="dim")
        header_text.append("  •  ", style="dim")
        header_text.append(f"{meta.diff_lines:,} diff lines", style="dim")
        
        panel = Panel(
            header_text,
            box=box.ROUNDED,
            padding=(0, 1),
        )
        self.console.print(panel)
        self.console.print()
    
    def _render_findings(self, result: CodeReviewResult) -> None:
        """Render findings grouped by file."""
        if not result.findings:
            self.console.print("[green]✓ No issues found![/green]")
            self.console.print()
            return
        
        # Group findings by file
        findings_by_file: dict[str, list[Finding]] = {}
        for finding in result.findings:
            if finding.file_path not in findings_by_file:
                findings_by_file[finding.file_path] = []
            findings_by_file[finding.file_path].append(finding)
        
        # Render each file's findings
        for file_path, findings in findings_by_file.items():
            self.console.print(f"[bold]📁 {file_path}[/bold]")
            
            for finding in findings:
                self._render_finding(finding)
            
            self.console.print()
    
    def _render_finding(self, finding: Finding) -> None:
        """Render a single finding."""
        emoji = SEVERITY_EMOJI.get(finding.severity, "⚪")
        color = SEVERITY_COLORS.get(finding.severity, "")
        category_abbrev = CATEGORY_ABBREV.get(finding.category, "???")
        
        # First line: severity, category, title, line number
        line_info = ""
        if finding.line_range:
            line_info = f"[dim]{finding.line_range}[/dim]"
        
        severity_text = finding.severity.value.upper()
        
        self.console.print(
            f"  {emoji} [{color}]{severity_text:8}[/{color}] "
            f"[dim]\\[[/dim]{category_abbrev}[dim]][/dim] "
            f"[bold]{finding.title}[/bold]   {line_info}"
        )
        
        # Description
        self.console.print(f"     [dim]{finding.description}[/dim]")
        
        # Suggested fix
        if finding.suggested_fix:
            # Keep fix on single line if short, otherwise wrap
            fix_text = finding.suggested_fix.strip()
            if len(fix_text) < 80 and "\n" not in fix_text:
                self.console.print(f"     [green]Fix:[/green] [cyan]{fix_text}[/cyan]")
            else:
                self.console.print(f"     [green]Fix:[/green]")
                for line in fix_text.split("\n"):
                    self.console.print(f"       [cyan]{line}[/cyan]")
        
        # References and confidence
        refs_and_conf = []
        if finding.references:
            refs_and_conf.append(" · ".join(finding.references))
        refs_and_conf.append(f"[dim]\\[conf: {finding.confidence:.2f}][/dim]")
        
        if refs_and_conf:
            self.console.print(f"     [dim]→[/dim] {' '.join(refs_and_conf)}")
        
        self.console.print()
    
    def _render_praise(self, result: CodeReviewResult) -> None:
        """Render the praise section."""
        if not result.praise:
            return
        
        self.console.print("[bold]✨ What's done well:[/bold]")
        for item in result.praise:
            self.console.print(f"   [green]•[/green] {item}")
        self.console.print()
    
    def _render_footer(
        self,
        result: CodeReviewResult,
        input_tokens: int,
        output_tokens: int
    ) -> None:
        """Render the footer with summary statistics."""
        self.console.print("─" * 54)
        
        # Count findings by severity
        counts = result.count_by_severity()
        
        # Risk level
        risk_color = SEVERITY_COLORS.get(result.overall_risk, "")
        risk_text = result.overall_risk.value.upper()
        
        # Build severity counts string
        severity_parts = []
        for sev in [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW]:
            count = counts[sev]
            if count > 0:
                emoji = SEVERITY_EMOJI[sev]
                severity_parts.append(f"{count} {sev.value}")
        
        severity_str = " · ".join(severity_parts) if severity_parts else "0 findings"
        
        self.console.print(
            f"  [bold]Risk:[/bold] [{risk_color}]{risk_text}[/{risk_color}]  |  "
            f"{severity_str}"
        )
        
        # Score indicator (simple calculation based on findings)
        score = self._calculate_score(result)
        score_style = "green" if score >= 80 else "yellow" if score >= 60 else "red"
        score_indicator = "✓" if score >= 80 else "⚠" if score >= 60 else "✗"
        
        score_message = "All clear!" if score >= 80 else \
                       "Minor issues" if score >= 60 else \
                       "Findings require attention"
        
        self.console.print(
            f"  [bold]Score:[/bold] [{score_style}]{score}/100  {score_indicator}[/{score_style}]  "
            f"{score_message}"
        )
        
        # Token usage and cost
        total_tokens = result.metadata.total_tokens
        cost = estimate_cost(input_tokens, output_tokens, result.metadata.model)
        cost_str = format_cost(cost)
        
        self.console.print(
            f"  [dim]Tokens: {total_tokens:,}  ({cost_str})  |  "
            f"Time: {result.metadata.processing_time_seconds}s[/dim]"
        )
    
    def _calculate_score(self, result: CodeReviewResult) -> int:
        """Calculate a simple health score based on findings.
        
        This is a rough heuristic - not a formal metric.
        """
        base_score = 100
        
        # Deduct points based on severity
        deductions = {
            Severity.CRITICAL: 30,
            Severity.HIGH: 15,
            Severity.MEDIUM: 7,
            Severity.LOW: 3,
            Severity.INFO: 1,
        }
        
        for finding in result.findings:
            base_score -= deductions.get(finding.severity, 0)
        
        return max(0, base_score)
    
    def _format_json(self, result: CodeReviewResult) -> str:
        """Format as JSON output."""
        return result.model_dump_json(indent=2)
    
    def _format_markdown(
        self,
        result: CodeReviewResult,
        input_tokens: int,
        output_tokens: int
    ) -> str:
        """Format as Markdown output."""
        lines = []
        
        # Header
        lines.append("# Code Review Results")
        lines.append("")
        meta = result.metadata
        lines.append(f"**Model:** {meta.model} | **Time:** {meta.processing_time_seconds}s")
        lines.append(f"**Files reviewed:** {meta.files_reviewed} | **Diff lines:** {meta.diff_lines:,}")
        lines.append("")
        
        # Summary
        lines.append(f"## Summary")
        lines.append("")
        lines.append(f"> {result.summary}")
        lines.append("")
        lines.append(f"**Overall Risk:** {result.overall_risk.value.upper()}")
        lines.append("")
        
        # Findings
        if result.findings:
            lines.append("## Findings")
            lines.append("")
            
            for finding in result.findings:
                severity_emoji = SEVERITY_EMOJI.get(finding.severity, "⚪")
                lines.append(f"### {severity_emoji} {finding.title}")
                lines.append("")
                lines.append(f"- **Severity:** {finding.severity.value}")
                lines.append(f"- **Category:** {finding.category.value}")
                lines.append(f"- **File:** `{finding.file_path}`")
                if finding.line_range:
                    lines.append(f"- **Lines:** {finding.line_range.start}-{finding.line_range.end}")
                lines.append(f"- **Confidence:** {finding.confidence:.2f}")
                lines.append("")
                lines.append(finding.description)
                lines.append("")
                
                if finding.suggested_fix:
                    lines.append("**Suggested Fix:**")
                    lines.append("```")
                    lines.append(finding.suggested_fix)
                    lines.append("```")
                    lines.append("")
                
                if finding.references:
                    lines.append(f"**References:** {', '.join(finding.references)}")
                    lines.append("")
        else:
            lines.append("## Findings")
            lines.append("")
            lines.append("✅ No issues found!")
            lines.append("")
        
        # Praise
        if result.praise:
            lines.append("## What's Done Well")
            lines.append("")
            for item in result.praise:
                lines.append(f"- {item}")
            lines.append("")
        
        # Footer
        cost = estimate_cost(input_tokens, output_tokens, result.metadata.model)
        lines.append("---")
        lines.append(f"*Tokens: {meta.total_tokens:,} | Cost: {format_cost(cost)}*")
        
        return "\n".join(lines)


def print_rich(
    result: CodeReviewResult,
    input_tokens: int = 0,
    output_tokens: int = 0,
    console: Optional[Console] = None
) -> None:
    """Convenience function to print rich output.
    
    Args:
        result: The CodeReviewResult to print
        input_tokens: Input token count for cost calculation
        output_tokens: Output token count for cost calculation
        console: Optional Rich Console instance
    """
    formatter = Formatter(console)
    formatter.format(result, "rich", input_tokens, output_tokens)


def to_json(result: CodeReviewResult) -> str:
    """Convenience function to convert result to JSON.
    
    Args:
        result: The CodeReviewResult to convert
        
    Returns:
        JSON string representation
    """
    return Formatter().format(result, "json")


def to_markdown(
    result: CodeReviewResult,
    input_tokens: int = 0,
    output_tokens: int = 0
) -> str:
    """Convenience function to convert result to Markdown.
    
    Args:
        result: The CodeReviewResult to convert
        input_tokens: Input token count for cost calculation
        output_tokens: Output token count for cost calculation
        
    Returns:
        Markdown string representation
    """
    return Formatter().format(result, "markdown", input_tokens, output_tokens)
