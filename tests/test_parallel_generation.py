"""Tests for parallel LLM page generation."""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from repoquill.config import LLMConfig, RepoQuillConfig
from repoquill.narrative import generate_all_pages


def _make_cfg(tmp_path, max_concurrent=1):
    """Create a minimal config for testing."""
    return RepoQuillConfig(
        project_name="test",
        package_dir="testpkg",
        root=str(tmp_path),
        llm=LLMConfig(max_concurrent=max_concurrent),
        out_guides=str(tmp_path / "guides"),
    )


def _make_pages(n=3):
    """Create n test pages."""
    return [
        {
            "slug": f"page-{i}",
            "title": f"Page {i}",
            "description": f"Description {i}",
            "source_files": [f"file{i}.py"],
        }
        for i in range(n)
    ]


def test_sequential_generation():
    """Test sequential generation (max_concurrent=1)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = __import__("pathlib").Path(tmp)
        cfg = _make_cfg(tmp_path, max_concurrent=1)
        pages = _make_pages(3)
        source_files = {f"file{i}.py": f"# file {i}" for i in range(3)}
        old_hashes = {}
        new_hashes = {f"file{i}.py": f"hash{i}" for i in range(3)}

        mock_client = MagicMock()
        mock_client.chat.return_value = "# Test Page\n\nContent"

        with patch("repoquill.narrative.page_needs_regeneration", return_value=True):
            generated = generate_all_pages(
                pages, source_files, mock_client, cfg, old_hashes, new_hashes
            )

        assert len(generated) == 3
        assert mock_client.chat.call_count == 3
        # Verify files were written
        for i in range(3):
            assert (tmp_path / "guides" / f"page-{i}.md").exists()


def test_parallel_generation():
    """Test parallel generation (max_concurrent=3)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = __import__("pathlib").Path(tmp)
        cfg = _make_cfg(tmp_path, max_concurrent=3)
        pages = _make_pages(3)
        source_files = {f"file{i}.py": f"# file {i}" for i in range(3)}
        old_hashes = {}
        new_hashes = {f"file{i}.py": f"hash{i}" for i in range(3)}

        mock_client = MagicMock()
        mock_client.chat.return_value = "# Test Page\n\nContent"

        with patch("repoquill.narrative.page_needs_regeneration", return_value=True):
            generated = generate_all_pages(
                pages, source_files, mock_client, cfg, old_hashes, new_hashes
            )

        assert len(generated) == 3
        assert mock_client.chat.call_count == 3
        # Verify files were written
        for i in range(3):
            assert (tmp_path / "guides" / f"page-{i}.md").exists()


def test_parallel_generation_with_failure():
    """Test that parallel generation handles failures gracefully."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = __import__("pathlib").Path(tmp)
        cfg = _make_cfg(tmp_path, max_concurrent=2)
        pages = _make_pages(3)
        source_files = {f"file{i}.py": f"# file {i}" for i in range(3)}
        old_hashes = {}
        new_hashes = {f"file{i}.py": f"hash{i}" for i in range(3)}

        mock_client = MagicMock()

        def side_effect(messages, **kwargs):
            # Fail on the second page
            if "Page 1" in messages[0]["content"]:
                raise Exception("LLM error")
            return "# Test Page\n\nContent"

        mock_client.chat.side_effect = side_effect

        with patch("repoquill.narrative.page_needs_regeneration", return_value=True):
            generated = generate_all_pages(
                pages, source_files, mock_client, cfg, old_hashes, new_hashes
            )

        # Only 2 pages should succeed (page 1 fails)
        assert len(generated) == 2
        assert "page-1" not in generated


def test_skip_unchanged_pages():
    """Test that unchanged pages are skipped."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = __import__("pathlib").Path(tmp)
        cfg = _make_cfg(tmp_path, max_concurrent=2)
        pages = _make_pages(3)
        source_files = {f"file{i}.py": f"# file {i}" for i in range(3)}
        old_hashes = {f"file{i}.py": f"hash{i}" for i in range(3)}
        new_hashes = {f"file{i}.py": f"hash{i}" for i in range(3)}  # Same hashes

        mock_client = MagicMock()

        with patch("repoquill.narrative.page_needs_regeneration", return_value=False):
            generated = generate_all_pages(
                pages, source_files, mock_client, cfg, old_hashes, new_hashes
            )

        assert len(generated) == 0
        assert mock_client.chat.call_count == 0
