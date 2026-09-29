def count_vowels(s: str) -> int:
    """Return how many vowels (a, e, i, o, u, in any case) s contains."""
    count = 0
    for char in s.lower():
        if char in "aeiou":
            count += 1
    return count
