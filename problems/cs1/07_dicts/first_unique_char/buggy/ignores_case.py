def first_unique_char(s: str) -> int:
    s = s.lower()  # bug: the spec says "a" and "A" are different characters
    counts = {}
    for char in s:
        counts[char] = counts.get(char, 0) + 1
    for index, char in enumerate(s):
        if counts[char] == 1:
            return index
    return -1
