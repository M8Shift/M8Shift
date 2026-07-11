"""Pinned oracle for the spec-implement-verify demo. Do not edit."""
import unittest

from reverse_words import reverse_words


class TestReverseWords(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(reverse_words("relay pen turn"), "turn pen relay")

    def test_single_word(self):
        self.assertEqual(reverse_words("m8shift"), "m8shift")

    def test_extra_whitespace_collapses(self):
        self.assertEqual(reverse_words("  a   b  c "), "c b a")

    def test_empty(self):
        self.assertEqual(reverse_words(""), "")


if __name__ == "__main__":
    unittest.main()
