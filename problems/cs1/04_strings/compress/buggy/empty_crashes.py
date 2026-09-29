def compress(s: str) -> str:
    parts = []
    current = s[0]  # bug: IndexError when s is "" (there is no first letter)
    count = 1
    for char in s[1:]:
        if char == current:
            count += 1
        else:
            parts.append(current + str(count))
            current = char
            count = 1
    parts.append(current + str(count))
    return "".join(parts)
