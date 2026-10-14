"""Tests for repoquill.core.manifest — per-page verified state + atomic plan store."""

import json
import os

import pytest

from repoquill.core.manifest import (
    mark_verified,
    page_is_verified,
    page_needs_update,
    record_page_failure,
    record_page_success,
    sha256_file,
    store_plan_atomic,
)
from repoquill.plan import compute_file_hashes, load_plan, store_plan


def _make_out(tmp_path, slug, content):
    out = tmp_path / f"{slug}.md"
    out.write_text(content)
    return str(out)


class TestAtomicStore:
    def test_roundtrip(self, tmp_path):
        plan_file = str(tmp_path / ".plan.json")
        plan = {"pages": [{"slug": "a"}], "file_hashes": {"x.py": "abc"}}
        store_plan_atomic(plan_file, plan)
        with open(plan_file) as f:
            assert json.load(f) == plan

    def test_overwrites_existing(self, tmp_path):
        plan_file = str(tmp_path / ".plan.json")
        store_plan_atomic(plan_file, {"pages": [], "file_hashes": {}})
        plan2 = {"pages": [{"slug": "b"}], "file_hashes": {"y.py": "def"}}
        store_plan_atomic(plan_file, plan2)
        assert load_plan(plan_file) == plan2

    def test_write_failure_mid_write_keeps_old_plan(self, tmp_path, monkeypatch):
        """A failure during the write must leave the existing plan intact
        and leave no temp-file litter behind."""
        plan_file = str(tmp_path / ".plan.json")
        old_plan = {"pages": [{"slug": "keep"}], "file_hashes": {"x.py": "abc"}}
        store_plan_atomic(plan_file, old_plan)
        old_content = open(plan_file).read()

        def _boom(*args, **kwargs):
            raise OSError("simulated disk failure mid-write")

        monkeypatch.setattr("repoquill.core.manifest.json.dump", _boom)

        with pytest.raises(OSError):
            store_plan_atomic(plan_file, {"pages": [], "file_hashes": {}})

        # Existing plan untouched.
        assert open(plan_file).read() == old_content
        assert load_plan(plan_file) == old_plan
        # No temp files littering the directory.
        entries = os.listdir(str(tmp_path))
        assert entries == [".plan.json"], entries

    def test_store_plan_delegates_atomically(self, tmp_path):
        """repoquill.plan.store_plan (legacy signature) must also be atomic."""
        plan_file = str(tmp_path / ".plan.json")
        old_plan = {"pages": [{"slug": "keep"}], "file_hashes": {"x.py": "abc"}}
        store_plan(plan_file, old_plan["pages"], old_plan["file_hashes"])
        old_content = open(plan_file).read()

        import repoquill.core.manifest as manifest_mod

        orig = manifest_mod.json.dump

        def _boom(*args, **kwargs):
            raise OSError("simulated disk failure mid-write")

        manifest_mod.json.dump = _boom
        try:
            with pytest.raises(OSError):
                store_plan(plan_file, [], {})
        finally:
            manifest_mod.json.dump = orig

        assert open(plan_file).read() == old_content
        assert os.listdir(str(tmp_path)) == [".plan.json"]


class TestRecordSuccess:
    def test_success_fields(self, tmp_path):
        out = _make_out(tmp_path, "a", "# Guide A\n")
        page = {"slug": "a", "title": "A", "source_files": ["x.py"]}
        record_page_success(page, out)
        assert page["status"] == "ok"
        assert page["content_sha256"] == sha256_file(out)
        assert page["error"] is None
        assert page["generated_at"]  # ISO timestamp present
        from datetime import datetime
        datetime.fromisoformat(page["generated_at"])  # parseable

    def test_success_cleared_error(self, tmp_path):
        out = _make_out(tmp_path, "a", "# Guide A\n")
        page = {"slug": "a", "status": "failed", "error": "old boom"}
        record_page_success(page, out)
        assert page["status"] == "ok"
        assert page["error"] is None

    def test_page_is_verified(self, tmp_path):
        out = _make_out(tmp_path, "a", "# Guide A\n")
        page = {"slug": "a", "source_files": ["x.py"]}
        assert not page_is_verified(page)
        record_page_success(page, out)
        # ok + content hash, but not yet marked verified
        assert not page_is_verified(page)
        mark_verified(page, {"x.py": "abc"})
        assert page_is_verified(page)


class TestRecordFailure:
    def test_failure_forces_update(self, tmp_path):
        page = {"slug": "b", "source_files": ["x.py"]}
        record_page_failure(page, "LLM timeout")
        assert page["status"] == "failed"
        assert page["error"] == "LLM timeout"
        # Forces regen even with no out_path and unchanged hashes.
        assert page_needs_update(page, {"x.py": "abc"}) is True

    def test_failure_with_partial_file_still_forces_update(self, tmp_path):
        out = _make_out(tmp_path, "b", "partial garbage\n")
        page = {"slug": "b", "source_files": ["x.py"]}
        record_page_failure(page, "LLM timeout")
        assert page_needs_update(page, {"x.py": "abc"}, out) is True


class TestContentHashMismatch:
    def test_intact_output_needs_no_update(self, tmp_path):
        out = _make_out(tmp_path, "a", "# Guide A\n")
        page = {"slug": "a", "source_files": ["x.py"]}
        record_page_success(page, out)
        mark_verified(page, {"x.py": "abc"})
        assert page_needs_update(page, {"x.py": "abc"}, out) is False

    def test_tampered_output_forces_update(self, tmp_path):
        out = _make_out(tmp_path, "a", "# Guide A\n")
        page = {"slug": "a", "source_files": ["x.py"]}
        record_page_success(page, out)
        mark_verified(page, {"x.py": "abc"})
        # Output modified after verification (tampered / regenerated away)
        with open(out, "w") as f:
            f.write("# Someone else's content\n")
        assert page_needs_update(page, {"x.py": "abc"}, out) is True

    def test_missing_output_forces_update(self, tmp_path):
        out = str(tmp_path / "a.md")
        _make_out(tmp_path, "a", "# Guide A\n")
        page = {"slug": "a", "source_files": ["x.py"]}
        record_page_success(page, out)
        mark_verified(page, {"x.py": "abc"})
        os.remove(out)
        assert page_needs_update(page, {"x.py": "abc"}, out) is True

    def test_source_change_forces_update(self, tmp_path):
        out = _make_out(tmp_path, "a", "# Guide A\n")
        page = {"slug": "a", "source_files": ["x.py"]}
        record_page_success(page, out)
        mark_verified(page, {"x.py": "abc"})
        # Source file changed since verification
        assert page_needs_update(page, {"x.py": "changed"}, out) is True
        # Untracked-in-page file change does not force an update
        assert page_needs_update(page, {"x.py": "abc", "z.py": "new"}, out) is False

    def test_new_untracked_source_file_forces_update(self, tmp_path):
        out = _make_out(tmp_path, "a", "# Guide A\n")
        page = {"slug": "a", "source_files": ["x.py", "y.py"]}
        record_page_success(page, out)
        mark_verified(page, {"x.py": "abc", "y.py": "def"})
        # y.py removed from the tracked set
        assert page_needs_update(page, {"x.py": "abc"}, out) is True
