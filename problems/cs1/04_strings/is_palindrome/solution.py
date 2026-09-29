def is_palindrome(s: str) -> bool:
    """Return True if s reads the same backwards (ignoring case, spaces and punctuation)."""
    cleaned = []
    for char in s:
        if char.isalnum():
            cleaned.append(char.lower())
    return cleaned == cleaned[::-1]
