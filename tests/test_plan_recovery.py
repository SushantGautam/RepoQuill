"""End-to-end retry story at plan level: failed pages must retry even when
no source file changed again, while successful pages stay skipped.

Covers the P0-1 bug: ``store_plan`` used to persist new hashes
unconditionally, so a page that failed generation was skipped forever on
subsequent runs because its hashes compared equal.
"""

import json
import os

from repoquill.core.manifest import (
    page_needs_update,
    record_page_failure,
    record_page_success,
    store_plan_atomic,
)
from repoquill.plan import (
    compute_file_hashes,
    load_plan,
    page_needs_regeneration,
    store_plan,
)

SOURCES = {
    "pkg/core.py": "def alpha():\n    return 1\n",
    "pkg/utils.py": "def beta():\n    return 2\n",
}
HASHES = compute_file_hashes(SOURCES)


def _plan_with_two_pages():
    page_a = {"slug": "guide-a", "title": "Guide A",
              "source_files": ["pkg/core.py"]}
    page_b = {"slug": "guide-b", "title": "Guide B",
              "source_files": ["pkg/utils.py"]}
    return page_a, page_b


def _persist_and_reload(tmp_path, pages, file_hashes):
    plan_file = str(tmp_path / ".plan.json")
    store_plan(plan_file, pages, file_hashes)
    return load_plan(plan_file), plan_file


def test_failed_page_retries_successful_page_stays_skipped(tmp_path):
    """A: success (file written + recorded); B: failure (file absent).
    No source hashes change between runs → B must still regenerate, A must not."""
    page_a, page_b = _plan_with_two_pages()

    # Run 1: A succeeds, B fails.
    out_a = tmp_path / "guide-a.md"
    out_a.write_text("# Guide A\n")
    record_page_success(page_a, str(out_a))
    page_a["verified_file_hashes"] = dict(HASHES)

    out_b = tmp_path / "guide-b.md"
    record_page_failure(page_b, "LLM generation failed")

    plan_file = str(tmp_path / ".plan.json")
    store_plan(plan_file, [page_a, page_b], HASHES)

    # Run 2: reload the persisted plan; source hashes are identical.
    reloaded = load_plan(plan_file)
    assert reloaded is not None
    assert reloaded["file_hashes"] == HASHES
    loaded_a, loaded_b = reloaded["pages"]
    current_hashes = compute_file_hashes(SOURCES)  # unchanged

    # A: must NOT regenerate.
    assert page_needs_update(loaded_a, current_hashes, str(out_a)) is False
    assert page_needs_regeneration(
        loaded_a, HASHES, current_hashes, str(out_a)
    ) is False

    # B: MUST regenerate, even though no source hashes changed.
    assert page_needs_update(loaded_b, current_hashes, str(out_b)) is True
    assert page_needs_regeneration(
        loaded_b, HASHES, current_hashes, str(out_b)
    ) is True

    # B's failure message survived the round trip.
    assert loaded_b["status"] == "failed"
    assert loaded_b["error"] == "LLM generation failed"
    assert loaded_a["status"] == "ok"
    assert loaded_a["content_sha256"]  # recorded fingerprint


def test_failed_page_with_partial_file_still_retries(tmp_path):
    """Even if a partial output file exists for the failed page, retry."""
    page_a, page_b = _plan_with_two_pages()

    out_a = tmp_path / "guide-a.md"
    out_a.write_text("# Guide A\n")
    record_page_success(page_a, str(out_a))
    page_a["verified_file_hashes"] = dict(HASHES)

    out_b = tmp_path / "guide-b.md"
    out_b.write_text("partial junk\n")  # partial output from the crash
    record_page_failure(page_b, "crashed mid-write")

    plan_file = str(tmp_path / ".plan.json")
    store_plan(plan_file, [page_a, page_b], HASHES)

    reloaded = load_plan(plan_file)
    current_hashes = compute_file_hashes(SOURCES)
    assert page_needs_update(reloaded["pages"][1], current_hashes, str(out_b)) is True
    assert page_needs_update(reloaded["pages"][0], current_hashes, str(out_a)) is False


def test_retry_after_failure_then_success(tmp_path):
    """B fails on run 1, succeeds on run 2 → after success B is stable again."""
    page_a, page_b = _plan_with_two_pages()

    out_a = tmp_path / "guide-a.md"
    out_a.write_text("# Guide A\n")
    record_page_success(page_a, str(out_a))
    page_a["verified_file_hashes"] = dict(HASHES)
    record_page_failure(page_b, "first attempt failed")

    plan_file = str(tmp_path / ".plan.json")
    store_plan(plan_file, [page_a, page_b], HASHES)
    assert page_needs_update(load_plan(plan_file)["pages"][1], HASHES) is True

    # Run 2: B is retried and succeeds.
    out_b = tmp_path / "guide-b.md"
    out_b.write_text("# Guide B\n")
    record_page_success(page_b, str(out_b))
    page_b["verified_file_hashes"] = dict(HASHES)
    store_plan(plan_file, [page_a, page_b], HASHES)

    reloaded = load_plan(plan_file)
    assert page_needs_update(reloaded["pages"][1], HASHES, str(out_b)) is False
    assert page_needs_regeneration(
        reloaded["pages"][1], HASHES, HASHES, str(out_b)
    ) is False


class TestLegacyPlanBackwardCompat:
    """Old plans (no status fields at all) keep today's exact semantics."""

    def _legacy_pages(self):
        return [
            {"slug": "guide-a", "title": "Guide A",
             "source_files": ["pkg/core.py"]},
            {"slug": "guide-b", "title": "Guide B",
             "source_files": ["pkg/utils.py"]},
        ]

    def test_unchanged_hashes_no_regeneration(self, tmp_path):
        pages = self._legacy_pages()
        out_a = tmp_path / "guide-a.md"
        out_a.write_text("# A\n")
        _, _ = _persist_and_reload(tmp_path, pages, HASHES)

        reloaded = load_plan(str(tmp_path / ".plan.json"))
        page = reloaded["pages"][0]
        assert page_needs_regeneration(page, HASHES, HASHES, str(out_a)) is False
        assert page_needs_update(page, HASHES, str(out_a)) is False

    def test_changed_hash_forces_regeneration(self, tmp_path):
        pages = self._legacy_pages()
        out_a = tmp_path / "guide-a.md"
        out_a.write_text("# A\n")
        _persist_and_reload(tmp_path, pages, HASHES)

        reloaded = load_plan(str(tmp_path / ".plan.json"))
        new_hashes = dict(HASHES)
        new_hashes["pkg/core.py"] = "different"
        page = reloaded["pages"][0]
        assert page_needs_regeneration(page, HASHES, new_hashes, str(out_a)) is True

    def test_missing_output_file_forces_regeneration(self, tmp_path):
        pages = self._legacy_pages()
        _persist_and_reload(tmp_path, pages, HASHES)

        reloaded = load_plan(str(tmp_path / ".plan.json"))
        page = reloaded["pages"][0]
        assert page_needs_regeneration(page, HASHES, HASHES,
                                       str(tmp_path / "guide-a.md")) is True

    def test_no_out_path_still_works(self, tmp_path):
        """page_needs_regeneration without out_path (narrative pre-check)."""
        pages = self._legacy_pages()
        _persist_and_reload(tmp_path, pages, HASHES)
        reloaded = load_plan(str(tmp_path / ".plan.json"))
        page = reloaded["pages"][0]
        assert page_needs_regeneration(page, HASHES, HASHES) is False
        new_hashes = dict(HASHES)
        new_hashes["pkg/core.py"] = "changed"
        assert page_needs_regeneration(page, HASHES, new_hashes) is True


def test_status_fields_roundtrip_shape_unchanged(tmp_path):
    """Top-level plan shape stays {"pages": [...], "file_hashes": {...}}."""
    page_a, page_b = _plan_with_two_pages()
    record_page_failure(page_b, "boom")
    plan_file = str(tmp_path / ".plan.json")
    store_plan(plan_file, [page_a, page_b], HASHES)
    with open(plan_file) as f:
        raw = json.load(f)
    assert set(raw.keys()) == {"pages", "file_hashes"}
    assert raw["file_hashes"] == HASHES
    assert [p["slug"] for p in raw["pages"]] == ["guide-a", "guide-b"]
