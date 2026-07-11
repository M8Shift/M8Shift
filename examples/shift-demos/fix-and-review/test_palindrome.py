"""Pinned oracle for the fix-and-review demo. Do not edit — fix palindrome.py."""
import unittest

from palindrome import is_palindrome


class TestIsPalindrome(unittest.TestCase):
    def test_simple(self):
        self.assertTrue(is_palindrome("level"))

    def test_case_insensitive(self):
        self.assertTrue(is_palindrome("Racecar"))

    def test_spaces_ignored(self):
        # Fails on the shipped bug: spaces are not removed before comparing.
        self.assertTrue(is_palindrome("never odd or even"))

    def test_negative(self):
        self.assertFalse(is_palindrome("m8shift relay"))


if __name__ == "__main__":
    unittest.main()
