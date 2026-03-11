"""Tests for CodeRev config module."""

import os
import textwrap
from pathlib import Path

import pytest

from coderev.config import (
    CONFIG_FILENAME,
    _deep_merge,
    _find_config,
    load_config,
    write_default_config,
)
from coderev.schema import CodeRevConfig, Severity


class TestDefaultConfig:
    """Tests for default config behaviour."""

    def test_default_config_is_valid(self):
        """Default config should be a valid CodeRevConfig."""
        cfg = CodeRevConfig.default()
        assert cfg.review.format == "rich"
        assert cfg.review.min_confidence == 0.0
        assert cfg.review.fail_on is None
        assert cfg.agents.enabled == ["security", "performance", "correctness"]
        assert cfg.exclude.paths == []
        assert cfg.eval.recall_threshold == 0.80

    def test_load_config_returns_defaults_when_no_file(self, tmp_path):
        """load_config should return all defaults when no config file exists."""
        cfg = load_config(project_dir=tmp_path)
        assert cfg.review.format == "rich"
        assert cfg.review.model == "moonshotai/kimi-k2-instruct"


class TestConfigFileLoading:
    """Tests for loading .coderev.toml files."""

    def test_load_partial_config(self, tmp_path):
        """A partial config should merge with defaults."""
        config_file = tmp_path / CONFIG_FILENAME
        config_file.write_text(
            textwrap.dedent("""\
                [review]
                fail_on = "high"
                min_confidence = 0.5
            """),
            encoding="utf-8",
        )
        cfg = load_config(project_dir=tmp_path)
        assert cfg.review.fail_on == Severity.HIGH
        assert cfg.review.min_confidence == 0.5
        # Defaults preserved
        assert cfg.review.format == "rich"
        assert cfg.agents.enabled == ["security", "performance", "correctness"]

    def test_load_full_config(self, tmp_path):
        """A complete config should be fully parsed."""
        config_file = tmp_path / CONFIG_FILENAME
        config_file.write_text(
            textwrap.dedent("""\
                [review]
                fail_on = "medium"
                min_confidence = 0.7
                format = "json"
                model = "custom/model"
                no_cache = true
                max_diff_lines = 3000

                [agents]
                enabled = ["security", "correctness"]

                [exclude]
                paths = ["vendor/", "generated/"]

                [eval]
                recall_threshold = 0.90
                precision_threshold = 0.80
            """),
            encoding="utf-8",
        )
        cfg = load_config(project_dir=tmp_path)
        assert cfg.review.fail_on == Severity.MEDIUM
        assert cfg.review.min_confidence == 0.7
        assert cfg.review.format == "json"
        assert cfg.review.model == "custom/model"
        assert cfg.review.no_cache is True
        assert cfg.review.max_diff_lines == 3000
        assert cfg.agents.enabled == ["security", "correctness"]
        assert cfg.exclude.paths == ["vendor/", "generated/"]
        assert cfg.eval.recall_threshold == 0.90

    def test_explicit_config_file_path(self, tmp_path):
        """config_file= parameter should override search."""
        custom = tmp_path / "my_config.toml"
        custom.write_text("[review]\nformat = \"markdown\"\n", encoding="utf-8")
        cfg = load_config(config_file=custom)
        assert cfg.review.format == "markdown"

    def test_invalid_toml_raises_value_error(self, tmp_path):
        """A malformed config file should raise ValueError."""
        config_file = tmp_path / CONFIG_FILENAME
        config_file.write_text("[[[[broken", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid .coderev.toml"):
            load_config(project_dir=tmp_path)

    def test_fail_on_none_string(self, tmp_path):
        """'none' should be parsed as None (no fail_on)."""
        config_file = tmp_path / CONFIG_FILENAME
        config_file.write_text(
            '[review]\nfail_on = "none"\n',
            encoding="utf-8",
        )
        cfg = load_config(project_dir=tmp_path)
        assert cfg.review.fail_on is None

    def test_fail_on_critical(self, tmp_path):
        """'critical' should be parsed as Severity.CRITICAL."""
        config_file = tmp_path / CONFIG_FILENAME
        config_file.write_text(
            '[review]\nfail_on = "critical"\n',
            encoding="utf-8",
        )
        cfg = load_config(project_dir=tmp_path)
        assert cfg.review.fail_on == Severity.CRITICAL


class TestConfigUpwardSearch:
    """Tests for walking up the directory tree to find config."""

    def test_finds_config_in_parent(self, tmp_path):
        """Config search should walk up to find .coderev.toml."""
        config_file = tmp_path / CONFIG_FILENAME
        config_file.write_text('[review]\nformat = "sarif"\n', encoding="utf-8")

        child = tmp_path / "src" / "sub"
        child.mkdir(parents=True)

        found = _find_config(child)
        assert found is not None
        assert found.name == CONFIG_FILENAME

    def test_returns_none_when_no_config(self, tmp_path):
        """Returns None when no config file exists anywhere."""
        child = tmp_path / "deep" / "nested"
        child.mkdir(parents=True)
        assert _find_config(child) is None


class TestDeepMerge:
    """Tests for the recursive dict merge utility."""

    def test_simple_merge(self):
        assert _deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    def test_override_takes_precedence(self):
        assert _deep_merge({"a": 1}, {"a": 2}) == {"a": 2}

    def test_nested_merge(self):
        base = {"review": {"fail_on": "high", "format": "rich"}}
        override = {"review": {"format": "json"}}
        result = _deep_merge(base, override)
        assert result == {"review": {"fail_on": "high", "format": "json"}}


class TestWriteDefaultConfig:
    """Tests for write_default_config."""

    def test_creates_file(self, tmp_path):
        path = tmp_path / CONFIG_FILENAME
        write_default_config(path)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "[review]" in content
        assert "fail_on" in content

    def test_content_is_valid_toml_comments(self, tmp_path):
        """Default config should be all comments (no active settings)."""
        path = tmp_path / CONFIG_FILENAME
        write_default_config(path)
        content = path.read_text(encoding="utf-8")
        for line in content.strip().splitlines():
            stripped = line.strip()
            if stripped:
                assert stripped.startswith("#") or stripped.startswith("["), (
                    f"Non-comment, non-section line found: {stripped!r}"
                )
