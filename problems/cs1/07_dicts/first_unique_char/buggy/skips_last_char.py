def first_unique_char(s: str) -> int:
    counts = {}
    for char in s:
        counts[char] = counts.get(char, 0) + 1
    for index in range(len(s) - 1):  # bug: never looks at the last character
        if counts[s[index]] == 1:
            return index
    return -1
