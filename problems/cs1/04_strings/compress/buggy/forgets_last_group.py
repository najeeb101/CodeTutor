def compress(s: str) -> str:
    if s == "":
        return ""
    parts = []
    current = s[0]
    count = 1
    for char in s[1:]:
        if char == current:
            count += 1
        else:
            parts.append(current + str(count))
            current = char
            count = 1
    return "".join(parts)  # bug: the last group is never saved, so "aaabcc" gives "a3b1"
