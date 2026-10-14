"""Text analysis utilities: word statistics and slug generation."""

import re


class TextStats:
    """Word-level statistics for a piece of text.

    The text is split on whitespace, so punctuation stays attached to
    words (e.g. ``"fox."`` is one word).

    Example:
        >>> stats = TextStats("The quick brown fox")
        >>> stats.word_count()
        4
        >>> stats.longest_word()
        'quick'
    """

    def __init__(self, text: str):
        """Store ``text`` and precompute its whitespace-split words."""
        self.text = text
        self._words = text.split()

    def word_count(self) -> int:
        """Return the number of whitespace-separated words in the text.

        Empty or whitespace-only text has a word count of 0.
        """
        return len(self._words)

    def longest_word(self) -> str:
        """Return the longest word in the text.

        Ties are broken by first occurrence. Returns ``""`` if the
        text contains no words.
        """
        longest = ""
        for word in self._words:
            if len(word) > len(longest):
                longest = word
        return longest


def slugify(text: str) -> str:
    """Convert arbitrary text into a URL-safe slug.

    Lowercases the text, keeps only alphanumeric characters and
    spaces/hyphens (collapsing runs of them into single hyphens), and
    strips leading/trailing hyphens.

    Example:
        >>> slugify("Hello, World!")
        'hello-world'
    """
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")
