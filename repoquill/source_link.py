"""Runtime patch: render mkdocstrings source labels as GitHub permalinks.

Griffe ≥ 2.2.0 exposes a ``source_link`` property on every parsed object,
computed from the repository's git remote URL and current commit hash.
The mkdocstrings-python handler has not yet wired this into its templates,
so the "Source code in" label shows a plain file path instead of a link.

This module provides two entry points:

1. ``install_source_link_patch()`` — patches the ``source_location`` Jinja
   filter in the mkdocstrings Python handler so that when an object has a
   ``source_link``, the label renders as a clickable hyperlink to the exact
   line range on GitHub/GitLab/etc.

2. ``run_mkdocs(command, args, cwd)`` — runs an mkdocs subcommand
   (``build``, ``serve``) in-process after installing the patch, so the
   patch is active when the handler initialises its Jinja environment.
"""

from __future__ import annotations

import logging
import sys

_log = logging.getLogger(__name__)

_installed = False


def install_source_link_patch() -> None:
    """Patch the mkdocstrings-python handler to use ``obj.source_link``.

    Safe to call multiple times — the patch is idempotent.
    Silently skips if the handler is not installed.
    """
    global _installed
    if _installed:
        return

    try:
        from mkdocstrings_handlers.python._internal import rendering
    except ImportError:
        return

    _orig = rendering.do_source_location

    def _patched_source_location(obj):
        """Return a GitHub/GitLab permalink when available, else the path."""
        link = getattr(obj, "source_link", None)
        if link:
            from markupsafe import Markup
            return Markup(
                f'<a href="{link}" target="_blank" rel="noopener" '
                f'style="color:inherit;text-decoration:underline">'
                f'{link}</a>'
            )
        return _orig(obj)

    rendering.do_source_location = _patched_source_location
    _installed = True
    _log.debug("source_link patch installed")


def run_mkdocs(command: str, args: list[str] | None = None, cwd: str | None = None) -> None:
    """Run an mkdocs subcommand in-process with the source-link patch active.

    This avoids the subprocess boundary that would prevent the in-process
    patch from taking effect.

    Args:
        command: The mkdocs subcommand (``"build"``, ``"serve"``, etc.).
        args: Additional CLI arguments (e.g. ``["-p", "8000"]``).
        cwd: Working directory for the mkdocs run.
    """
    import os
    if cwd:
        os.chdir(cwd)

    install_source_link_patch()

    from mkdocs.__main__ import cli as mkdocs_cli
    mkdocs_cli([command, *(args or [])], standalone_mode=False)
