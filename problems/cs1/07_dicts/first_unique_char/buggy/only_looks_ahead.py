def first_unique_char(s: str) -> int:
    for index in range(len(s)):
        if s[index] not in s[index + 1 :]:  # bug: forgets copies that came earlier
            return index
    return -1
