def compress(s: str) -> str:
    """Return the run-length encoding of s, for example "aaabcc" -> "a3b1c2"."""
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
    parts.append(current + str(count))  # the last group has no different letter after it
    return "".join(parts)
