def is_palindrome(s: str) -> bool:
    cleaned = []
    for char in s:
        if char.isalnum():
            cleaned.append(char)  # bug: forgot .lower(), so "A" and "a" are different
    return cleaned == cleaned[::-1]
