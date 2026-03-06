"""Tests for CodeRev utils module."""

import pytest

from coderev.utils import (
    detect_language,
    detect_languages_in_diff,
    estimate_cost,
    extract_files_from_diff,
    format_cost,
    get_severity_exit_code,
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
        cost = estimate_cost(1000, 500, "kimi-k2-0528")
        assert cost == 0.0021
    
    def test_llama_scout_cost(self):
        """Test cost calculation for Llama 4 Scout fallback model."""
        # 1000 input tokens at $0.0000001 = $0.0001
        # 500 output tokens at $0.0000001 = $0.00005
        # Total = $0.00015 -> rounds to $0.0001 (4 decimal places)
        cost = estimate_cost(1000, 500, "llama-4-scout")
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
