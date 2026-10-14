"""Markdown code-block extraction with file line numbers.

``repoquill.verify.extract_code_blocks`` finds fenced blocks but drops
line positions, which the quality gate needs to report actionable
findings. This module re-extracts the same fences and keeps, for each
block, the language tag and the 1-based file line of the first code
line (the line immediately after the opening fence).
"""

from __future__ import annotations

from typing import List, Tuple

#: Language tags treated as executable Python.
PYTHON_LANGS = ("", "python", "py")


def extract_code_blocks(md: str) -> List[Tuple[str, int, str]]:
    """Return ``(language, first_code_line, code)`` for every fenced block.

    ``language`` is the lowercase info-string word after the opening
    fence ("" for a bare ```` ``` ```` fence). ``first_code_line`` is the
    1-based line number in the source document of the first code line,
    so the file line of the i-th code line is ``first_code_line + i``.
    """
    blocks: List[Tuple[str, int, str]] = []
    lang = ""
    start = 0
    buf: List[str] = []
    in_fence = False
    for lineno, line in enumerate(md.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            if in_fence:
                blocks.append((lang, start, "\n".join(buf)))
                in_fence = False
            else:
                rest = stripped[3:].strip()
                lang = rest.split()[0].lower() if rest else ""
                start = lineno + 1
                buf = []
                in_fence = True
        elif in_fence:
            buf.append(line)
    # Unterminated fence: keep the partial block (fail loudly downstream).
    if in_fence:
        blocks.append((lang, start, "\n".join(buf)))
    return blocks


def python_blocks(md: str) -> List[Tuple[int, str]]:
    """Return ``(first_code_line, code)`` for Python-typed blocks only."""
    return [(start, code) for lang, start, code in extract_code_blocks(md)
            if lang in PYTHON_LANGS]
