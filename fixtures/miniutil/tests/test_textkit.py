"""Tests for miniutil.textkit."""

from miniutil.textkit import TextStats, slugify


def test_word_count_basic():
    assert TextStats("The quick brown fox").word_count() == 4


def test_word_count_empty():
    assert TextStats("").word_count() == 0
    assert TextStats("   ").word_count() == 0


def test_longest_word_basic():
    assert TextStats("The quick brown fox").longest_word() == "quick"


def test_longest_word_tie_goes_to_first():
    assert TextStats("cat dog").longest_word() == "cat"


def test_longest_word_empty():
    assert TextStats("").longest_word() == ""


def test_slugify_basic():
    assert slugify("Hello, World!") == "hello-world"


def test_slugify_collapse_and_strip():
    assert slugify("  --Foo___Bar--  ") == "foo-bar"


def test_slugify_digits_kept():
    assert slugify("Release 2.0 is out") == "release-2-0-is-out"
