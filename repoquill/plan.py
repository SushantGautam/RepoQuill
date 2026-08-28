"""Plan and hash-cache management for incremental generation.

The plan (``.plan.json``) stores the list of narrative pages and SHA-256
hashes of the source files each page depends on. On each run:

- The plan is reused while the tracked file set is unchanged.
- A page is skipped when none of its source files changed.
- Stale pages (in the old plan but not the current one) are deleted.

This is what makes Layer 2 (LLM) generation incremental and cheap: only
pages whose underlying source actually changed are sent to the LLM.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Dict, List, Optional


def compute_file_hashes(source_files: Dict[str, str]) -> Dict[str, str]:
    """Compute SHA-256 hashes for a mapping of {relative_path: content}.

    Args:
        source_files: Mapping of file path to file content.

    Returns:
        Mapping of file path to its SHA-256 hex digest.
    """
    return {path: hashlib.sha256(content.encode()).hexdigest()
            for path, content in source_files.items()}


def load_plan(plan_file: str) -> Optional[dict]:
    """Load the plan from disk, or None if it doesn't exist.

    Args:
        plan_file: Path to ``.plan.json``.

    Returns:
        The plan dict, or None if the file is missing/invalid.
    """
    if os.path.exists(plan_file):
        try:
            with open(plan_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
    return None


def store_plan(plan_file: str, pages: List[dict], file_hashes: Dict[str, str]) -> None:
    """Write the plan to disk.

    Args:
        plan_file: Path to ``.plan.json``.
        pages: List of page dicts (slug, title, source_files, ...).
        file_hashes: Current hashes of all tracked source files.
    """
    plan = {"pages": pages, "file_hashes": file_hashes}
    with open(plan_file, "w") as f:
        json.dump(plan, f, indent=2)


def page_needs_regeneration(
    page: dict, old_hashes: Dict[str, str], new_hashes: Dict[str, str],
    out_path: Optional[str] = None,
) -> bool:
    """Determine whether a page's source files have changed.

    Args:
        page: Page dict with a ``source_files`` list.
        old_hashes: Hashes from the previous plan.
        new_hashes: Hashes of the current source files.
        out_path: Optional path to the output .md file. If provided and
            the file is missing, regeneration is forced.

    Returns:
        True if any of the page's source files changed (or are new),
        or if the output file is missing.
    """
    # Force regeneration if the output file doesn't exist
    if out_path is not None and not os.path.exists(out_path):
        return True
    for f in page.get("source_files", []):
        old = old_hashes.get(f)
        new = new_hashes.get(f)
        if old is None or new is None or old != new:
            return True
    return False


def cleanup_stale_pages(plan_slugs: List[str], guides_dir: str) -> List[str]:
    """Delete guide pages that are no longer in the plan.

    Args:
        plan_slugs: Slugs present in the current plan.
        guides_dir: Directory containing the guide ``.md`` files.

    Returns:
        List of slugs that were deleted.
    """
    stale = []
    for fname in os.listdir(guides_dir):
        if not fname.endswith(".md"):
            continue
        slug = fname[:-3]
        if slug not in plan_slugs:
            os.remove(os.path.join(guides_dir, fname))
            stale.append(fname)
    return stale
