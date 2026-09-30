def first_unique_char(s: str) -> int:
    """Return the index of the first character that appears exactly once in s, or -1."""
    # Pass 1: count every character. One pass alone can't know about copies further on.
    counts = {}
    for char in s:
        counts[char] = counts.get(char, 0) + 1
    # Pass 2: the first position whose character appears only once.
    for index, char in enumerate(s):
        if counts[char] == 1:
            return index
    return -1
