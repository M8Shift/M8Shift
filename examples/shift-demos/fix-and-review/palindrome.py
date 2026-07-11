"""Demo module — contains ONE known bug for the fix-and-review exercise."""


def is_palindrome(text):
    """True when `text` reads the same forwards and backwards,
    ignoring case and spaces."""
    cleaned = text.lower()          # BUG: spaces are not removed
    return cleaned == cleaned[::-1]
