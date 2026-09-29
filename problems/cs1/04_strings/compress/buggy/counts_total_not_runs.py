def compress(s: str) -> str:
    result = ""
    for char in s:
        if char not in result:
            result += char + str(s.count(char))  # bug: counts every "a" in s, not one group
    return result
