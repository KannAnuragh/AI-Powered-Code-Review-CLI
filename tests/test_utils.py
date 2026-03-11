"""Tests for CodeRev utils module."""

import pytest

from coderev.utils import (
    build_diff_position_map,
    detect_language,
    detect_languages_in_diff,
    estimate_cost,
    extract_files_from_diff,
    format_cost,
    get_severity_exit_code,
    read_diff_from_stdin,
)
from coderev.schema import Finding, Category, Severity


class TestDetectLanguage:
    """Tests for language detection."""
    
    def test_python_files(self):
        """Test Python file detection."""
        assert detect_language("main.py") == "Python"
        assert detect_language("src/utils.py") == "Python"
        assert detect_language("types.pyi") == "Python"
    
    def test_javascript_typescript(self):
        """Test JS/TS file detection."""
        assert detect_language("app.js") == "JavaScript"
        assert detect_language("app.ts") == "TypeScript"
        assert detect_language("Component.tsx") == "TypeScript (React)"
        assert detect_language("Component.jsx") == "JavaScript (React)"
    
    def test_other_languages(self):
        """Test other language detection."""
        assert detect_language("main.go") == "Go"
        assert detect_language("main.rs") == "Rust"
        assert detect_language("Main.java") == "Java"
        assert detect_language("app.rb") == "Ruby"
    
    def test_special_files(self):
        """Test special filenames without extensions."""
        assert detect_language("Dockerfile") == "Dockerfile"
        assert detect_language("Makefile") == "Makefile"
    
    def test_unknown_extension(self):
        """Test unknown file extension."""
        assert detect_language("file.xyz") == "Unknown"
        assert detect_language("noextension") == "Unknown"


class TestExtractFilesFromDiff:
    """Tests for diff file extraction."""
    
    def test_git_diff_format(self):
        """Test extracting files from git diff format."""
        diff = """diff --git a/src/main.py b/src/main.py
index 1234567..abcdefg 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1,3 +1,4 @@
+import os
 def main():
     pass
"""
        files = extract_files_from_diff(diff)
        assert "src/main.py" in files
    
    def test_multiple_files(self):
        """Test extracting multiple files from diff."""
        diff = """diff --git a/file1.py b/file1.py
--- a/file1.py
+++ b/file1.py
@@ -1 +1 @@
-old
+new
diff --git a/file2.py b/file2.py
--- a/file2.py
+++ b/file2.py
@@ -1 +1 @@
-old
+new
"""
        files = extract_files_from_diff(diff)
        assert len(files) == 2
        assert "file1.py" in files
        assert "file2.py" in files
    
    def test_empty_diff(self):
        """Test empty diff returns empty list."""
        files = extract_files_from_diff("")
        assert files == []


class TestEstimateCost:
    """Tests for cost estimation."""
    
    def test_kimi_k2_cost(self):
        """Test cost calculation for Kimi K2 model."""
        # 1000 input tokens at $0.0000014 = $0.0014
        # 500 output tokens at $0.0000014 = $0.0007
        # Total = $0.0021
        cost = estimate_cost(1000, 500, "moonshotai/kimi-k2-instruct")
        assert cost == 0.0021
    
    def test_llama_scout_cost(self):
        """Test cost calculation for Llama 4 Scout fallback model."""
        # 1000 input tokens at $0.0000001 = $0.0001
        # 500 output tokens at $0.0000001 = $0.00005
        # Total = $0.00015 -> rounds to $0.0001 (4 decimal places)
        cost = estimate_cost(1000, 500, "meta-llama/llama-4-scout-17b-16e-instruct")
        assert cost == 0.0001
    
    def test_unknown_model_defaults_to_kimi_k2(self):
        """Test that unknown models default to Kimi K2 pricing."""
        cost = estimate_cost(1000, 500, "unknown-model")
        assert cost == 0.0021  # Same as Kimi K2


class TestFormatCost:
    """Tests for cost formatting."""
    
    def test_very_small_cost(self):
        """Test formatting very small costs."""
        assert format_cost(0.0001) == "<$0.001"
    
    def test_small_cost(self):
        """Test formatting small costs."""
        assert format_cost(0.005) == "~$0.005"
    
    def test_normal_cost(self):
        """Test formatting normal costs."""
        assert format_cost(0.023) == "~$0.02"

    def test_costs_above_threshold_show_approximate(self):
        """Costs >= $0.01 use approximate prefix."""
        assert format_cost(0.05).startswith("~$")

    def test_costs_below_threshold_show_less_than(self):
        """Costs < $0.001 use less-than prefix."""
        assert format_cost(0.0001).startswith("<$")


class TestGetSeverityExitCode:
    """Tests for exit code determination."""
    
    @pytest.fixture
    def findings_with_critical(self):
        """Create findings including critical severity."""
        return [
            Finding(
                category=Category.SECURITY,
                severity=Severity.CRITICAL,
                file_path="test.py",
                title="Critical issue here",
                description="Description",
                confidence=0.9,
            ),
            Finding(
                category=Category.STYLE,
                severity=Severity.LOW,
                file_path="test.py",
                title="Minor style issue",
                description="Description",
                confidence=0.8,
            ),
        ]
    
    @pytest.fixture
    def findings_medium_only(self):
        """Create findings with medium severity only."""
        return [
            Finding(
                category=Category.PERFORMANCE,
                severity=Severity.MEDIUM,
                file_path="test.py",
                title="Performance issue",
                description="Description",
                confidence=0.7,
            ),
        ]
    
    def test_fail_on_critical_with_critical(self, findings_with_critical):
        """Test exit code 1 when critical found and fail-on=critical."""
        assert get_severity_exit_code(findings_with_critical, "critical") == 1
    
    def test_fail_on_critical_without_critical(self, findings_medium_only):
        """Test exit code 0 when no critical found and fail-on=critical."""
        assert get_severity_exit_code(findings_medium_only, "critical") == 0
    
    def test_fail_on_medium_with_medium(self, findings_medium_only):
        """Test exit code 1 when medium found and fail-on=medium."""
        assert get_severity_exit_code(findings_medium_only, "medium") == 1
    
    def test_fail_on_low(self, findings_with_critical):
        """Test exit code 1 when any finding above low threshold."""
        assert get_severity_exit_code(findings_with_critical, "low") == 1
    
    def test_empty_findings(self):
        """Test exit code 0 with no findings."""
        assert get_severity_exit_code([], "critical") == 0


class TestDetectLanguagesInDiff:
    """Tests for detecting multiple languages in diff."""
    
    def test_multiple_languages(self):
        """Test detecting multiple languages."""
        diff = """diff --git a/main.py b/main.py
+++ b/main.py
diff --git a/app.ts b/app.ts
+++ b/app.ts
diff --git a/style.css b/style.css
+++ b/style.css
"""
        languages = detect_languages_in_diff(diff)
        assert "Python" in languages
        assert "TypeScript" in languages
        assert "CSS" in languages
    
    def test_unknown_excluded(self):
        """Test that Unknown is excluded from results."""
        diff = """diff --git a/main.py b/main.py
+++ b/main.py
diff --git a/file.xyz b/file.xyz
+++ b/file.xyz
"""
        languages = detect_languages_in_diff(diff)
        assert "Python" in languages
        assert "Unknown" not in languages


class TestDiffPositionMap:
    """Tests for the diff position mapper used by inline PR comments."""

    def test_added_line_gets_position(self):
        diff = (
            "diff --git a/app.py b/app.py\n"
            "+++ b/app.py\n"
            "@@ -0,0 +1,3 @@\n"
            "+def hello():\n"
            "+    return 1\n"
            "+\n"
        )
        pos_map = build_diff_position_map(diff)
        assert ("app.py", 1) in pos_map

    def test_removed_line_not_in_map(self):
        diff = (
            "+++ b/app.py\n"
            "@@ -1,2 +1,1 @@\n"
            "-old_line\n"
            "+new_line\n"
        )
        pos_map = build_diff_position_map(diff)
        assert ("app.py", 1) in pos_map

    def test_context_lines_in_map(self):
        diff = (
            "+++ b/app.py\n"
            "@@ -5,3 +5,4 @@\n"
            " context_line\n"
            "+added_line\n"
            " another_context\n"
        )
        pos_map = build_diff_position_map(diff)
        assert ("app.py", 5) in pos_map
        assert ("app.py", 6) in pos_map
        assert ("app.py", 7) in pos_map

    def test_multiple_files_in_map(self):
        diff = (
            "+++ b/file_a.py\n"
            "@@ -0,0 +1,2 @@\n"
            "+line_a_1\n"
            "+line_a_2\n"
            "+++ b/file_b.py\n"
            "@@ -0,0 +1,1 @@\n"
            "+line_b_1\n"
        )
        pos_map = build_diff_position_map(diff)
        assert ("file_a.py", 1) in pos_map
        assert ("file_a.py", 2) in pos_map
        assert ("file_b.py", 1) in pos_map

    def test_empty_diff_returns_empty_map(self):
        assert build_diff_position_map("") == {}

    def test_renamed_file_accessible_by_both_names(self):
        """Renamed files should be reachable via old and new name."""
        diff = (
            "diff --git a/old_name.py b/new_name.py\n"
            "similarity index 95%\n"
            "rename from old_name.py\n"
            "rename to new_name.py\n"
            "--- a/old_name.py\n"
            "+++ b/new_name.py\n"
            "@@ -1,3 +1,3 @@\n"
            " unchanged\n"
            "-old_line\n"
            "+new_line\n"
            " more_context\n"
        )
        pos_map = build_diff_position_map(diff)
        # New name is in the map
        assert ("new_name.py", 1) in pos_map
        # Old name is also in the map (alias)
        assert ("old_name.py", 1) in pos_map
        # Both resolve to the same diff position
        assert pos_map[("new_name.py", 2)] == pos_map[("old_name.py", 2)]


class TestReadDiffFromStdin:
    """Tests for reading diff content from stdin."""

    def test_returns_content_when_piped(self, monkeypatch):
        """When stdin is not a TTY, read and return its content."""
        import io
        fake_stdin = io.StringIO("diff --git a/f.py b/f.py\n")
        fake_stdin.isatty = lambda: False
        monkeypatch.setattr("coderev.utils.sys.stdin", fake_stdin)
        assert read_diff_from_stdin() == "diff --git a/f.py b/f.py\n"

    def test_returns_none_when_tty(self, monkeypatch):
        """When stdin is a TTY (interactive), return None."""
        import io
        fake_stdin = io.StringIO()
        fake_stdin.isatty = lambda: True
        monkeypatch.setattr("coderev.utils.sys.stdin", fake_stdin)
        assert read_diff_from_stdin() is None

    def test_returns_empty_string_for_empty_pipe(self, monkeypatch):
        """An empty pipe should return an empty string, not None."""
        import io
        fake_stdin = io.StringIO("")
        fake_stdin.isatty = lambda: False
        monkeypatch.setattr("coderev.utils.sys.stdin", fake_stdin)
        assert read_diff_from_stdin() == ""
