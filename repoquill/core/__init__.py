"""RepoQuill core — small, stateless building blocks for the pipeline.

Submodules here (``manifest``, ``impact``, ...) are intentionally dumb and
dependency-free so the CLI integration layer can compose them. Other
workers may add sibling submodules; import them directly
(``repoquill.core.<module>``) rather than re-exporting them here.
"""

from repoquill.core.manifest import (
    mark_verified,
    page_is_verified,
    page_needs_update,
    record_page_failure,
    record_page_success,
    sha256_file,
    store_plan_atomic,
)

__all__ = [
    "mark_verified",
    "page_is_verified",
    "page_needs_update",
    "record_page_failure",
    "record_page_success",
    "sha256_file",
    "store_plan_atomic",
]
