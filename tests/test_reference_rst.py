"""Regression tests for Sphinx/RST -> Markdown reference rendering.

The deterministic reference renderer must not leak Sphinx roles
(``:class:``, ``:meth:``, ...), RST inline literals (```` ``x`` ````),
numpydoc section underlines (``-----``), or turn ``**kwargs`` parameter
names into italic/bold. These leaks caused raw RST to appear in published
MkDocs reference pages (e.g. ``:class:`~simpleaudit.targets.Target` `` and
``----------`` showing verbatim).
"""
import os
import tempfile
import textwrap

from repoquill.reference import (
    _format_docstring,
    _render_module_via_ast,
    _rst_to_markdown,
)


def test_rst_roles_become_code_spans():
    out = _rst_to_markdown(
        "See :class:`ModelAuditor` and :meth:`~simpleaudit.utils.run_sync`."
    )
    assert ":class:" not in out
    assert ":meth:" not in out
    assert "`ModelAuditor`" in out
    # A leading ~ keeps only the last dotted component (Sphinx short-name).
    assert "`run_sync`" in out
    assert "simpleaudit.utils.run_sync" not in out


def test_rst_roles_without_tilde_keep_full_path():
    out = _rst_to_markdown("See :data:`simpleaudit.model_auditor.OnTurn`.")
    assert "`simpleaudit.model_auditor.OnTurn`" in out
    assert ":data:" not in out


def test_double_backtick_literal_to_single():
    out = _rst_to_markdown("The ``target`` argument is required.")
    assert "``" not in out
    assert "`target`" in out


def test_triple_backtick_inline_to_single():
    out = _rst_to_markdown("Markdown code blocks (```json ... ```).")
    assert "```" not in out
    assert "`json" in out


def test_numpydoc_underline_dropped():
    doc = "Doc.\n\nParameters\n----------\ntarget:\n    desc.\n"
    out = _rst_to_markdown(doc)
    assert "----------" not in out
    assert "Parameters" in out


def test_rst_to_markdown_is_idempotent():
    once = _rst_to_markdown("Use :class:`X` and ``y``.\n\nNotes\n-----\nMore.")
    twice = _rst_to_markdown(once)
    assert once == twice


def test_format_docstring_sections_and_kwargs():
    doc = textwrap.dedent(
        """\
        Parameters
        ----------
        target:
            Any :class:`Target`. Required.
        **kwargs:
            Forwarded to :class:`ModelAuditor`.
        """
    )
    out = "\n".join(_format_docstring(doc))
    assert "**Parameters**" in out
    assert ":class:" not in out
    assert "`Target`" in out
    # ``**kwargs`` must become a code span, never italic *kwargs*.
    assert "`**kwargs`" in out
    assert "*kwargs*" not in out
    assert "----------" not in out


def test_ast_render_is_rst_clean_and_rich():
    src = textwrap.dedent(
        '''
        """Module doc with :class:`Thing` and a ``x`` literal."""

        class Thing:
            """A thing.

            Parameters
            ----------
            target:
                Any :class:`Target`.
            **kwargs:
                Forwarded on.
            """

            def __init__(self, target: "Target", **kwargs):
                self.target = target

            def run(self, name: str) -> int:
                """Run ``name`` and return a count."""
                return 0
        '''
    )
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "thing.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(src)
        out = _render_module_via_ast("thing", path, {"thing": "desc"})

    # No raw Sphinx/RST artifacts leak into the rendered Markdown.
    assert ":class:" not in out
    assert "``" not in out
    assert "----------" not in out
    assert "*kwargs*" not in out
    assert "`**kwargs`" in out
    assert "`Target`" in out
    # Methods are listed, with return annotations and self dropped.
    assert "run(name: str) -> int" in out
    assert "run(self" not in out
    # The double-backtick literal in the run() docstring is cleaned.
    assert "`name`" in out
