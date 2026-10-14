"""Per-page verified state (manifest) for retry-safe incremental generation.

The plan file (``.plan.json``) stores, in addition to the legacy
``{"pages": [...], "file_hashes": {...}}`` shape, optional per-page fields
so a page that failed to generate (or verify) is retried on the next run
even when no source file changed again:

- ``"status"``: ``"ok"`` | ``"failed"``
- ``"content_sha256"``: SHA-256 of the successfully generated ``.md`` output
- ``"verified_file_hashes"``: source-file hashes in effect when the page
  last SUCCEEDED (and was verified)
- ``"error"``: failure message or ``None``
- ``"generated_at"``: ISO-8601 timestamp of the last successful generation

Old plans without these fields load and behave exactly as before; the
functions below fall back to legacy semantics when the fields are absent.

This module is deliberately small and stateless: it only inspects/mutates
the passed-in page dict and writes the plan atomically. No LLM, no config.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Dict, Optional


def sha256_file(path: str) -> str:
    """Return the SHA-256 hex digest of a file's contents.

    Args:
        path: Path to the file.

    Returns:
        Hex digest of the file contents.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_page_success(page: dict, out_path: str) -> None:
    """Record that ``page`` generated successfully to ``out_path``.

    Mutates ``page`` in place: sets ``status="ok"``,
    ``content_sha256`` (hash of ``out_path``), ``generated_at`` (UTC ISO
    timestamp), and clears ``error``.

    Args:
        page: The page dict (mutated in place).
        out_path: Path to the generated ``.md`` output (must exist).
    """
    page["status"] = "ok"
    page["content_sha256"] = sha256_file(out_path)
    page["generated_at"] = _utcnow_iso()
    page["error"] = None


def record_page_failure(page: dict, error: str) -> None:
    """Record that ``page`` failed; it must be retried on the next run.

    Mutates ``page`` in place: sets ``status="failed"`` and ``error``.
    ``content_sha256`` is cleared because the on-disk output (if any) is
    no longer verified content.

    Args:
        page: The page dict (mutated in place).
        error: Human-readable failure message.
    """
    page["status"] = "failed"
    page["error"] = error
    page["content_sha256"] = None


def mark_verified(page: dict, file_hashes: Dict[str, str]) -> None:
    """Record which source hashes ``page`` was last verified against.

    Mutates ``page`` in place: sets ``verified_file_hashes`` to a copy of
    ``file_hashes`` (the hashes of the tracked source files in effect when
    this page last succeeded AND passed verification).

    Args:
        page: The page dict (mutated in place).
        file_hashes: Mapping of source file path to SHA-256 hex digest.
    """
    page["verified_file_hashes"] = dict(file_hashes)


def page_is_verified(page: dict) -> bool:
    """Return True if ``page`` last succeeded, was verified, and its
    content fingerprint is recorded.

    Args:
        page: The page dict.

    Returns:
        True if status is ``"ok"``, a ``content_sha256`` is recorded, and
        ``verified_file_hashes`` is present.
    """
    return (
        page.get("status") == "ok"
        and bool(page.get("content_sha256"))
        and page.get("verified_file_hashes") is not None
    )


def page_needs_update(
    page: dict, current_file_hashes: Dict[str, str], out_path: Optional[str] = None,
) -> bool:
    """Decide whether ``page`` must be (re)generated.

    Regeneration is forced when ANY of:
      (a) ``page["status"] == "failed"`` — a previous attempt failed;
      (b) ``out_path`` is missing;
      (c) ``out_path`` exists but its SHA-256 differs from the recorded
          ``content_sha256`` (output tampered with / regenerated away);
      (d) any source file in ``page["source_files"]`` has a hash different
          from the recorded ``verified_file_hashes``.

    For legacy pages without ``verified_file_hashes`` (pre-status plans),
    check (d) cannot be evaluated from the page alone: the common checks
    (a)-(c) still apply, and the caller (e.g.
    ``repoquill.plan.page_needs_regeneration``) applies the legacy
    old-vs-new hash comparison.

    Args:
        page: Page dict (may be a legacy page without status fields).
        current_file_hashes: Current hashes of tracked source files.
        out_path: Optional path to the output ``.md`` file.

    Returns:
        True if the page needs (re)generation.
    """
    # (a) A previous attempt failed — always retry, even if sources are
    # unchanged since the failure.
    if page.get("status") == "failed":
        return True

    # (b) Missing output file.
    if out_path is not None and not os.path.exists(out_path):
        return True

    # (c) Output file exists but no longer matches the recorded content.
    content_sha = page.get("content_sha256")
    if out_path is not None and content_sha:
        if sha256_file(out_path) != content_sha:
            return True

    # (d) Source hashes since last verified success.
    verified = page.get("verified_file_hashes")
    if verified is None:
        # Legacy page: nothing page-local to compare; caller decides.
        return False
    for f in page.get("source_files", []):
        old = verified.get(f)
        new = current_file_hashes.get(f)
        if old is None or new is None or old != new:
            return True
    return False


def store_plan_atomic(plan_file: str, plan: dict) -> None:
    """Write ``plan`` to ``plan_file`` atomically.

    The plan is written to a temp file in the same directory, fsynced,
    then ``os.replace``d over the target. A crash or write failure
    mid-write never corrupts an existing plan file, and no temp files are
    left behind.

    Args:
        plan_file: Destination path (e.g. ``.plan.json``).
        plan: Plan dict (typically ``{"pages": [...], "file_hashes": {...}}``).
    """
    directory = os.path.dirname(os.path.abspath(plan_file)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".plan-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, plan_file)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
