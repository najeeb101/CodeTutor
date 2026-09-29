def is_palindrome(s: str) -> bool:
    cleaned = []
    for char in s:
        if char.isalnum():
            cleaned.append(char.lower())
    if not cleaned:
        return False  # bug: the spec says empty text (after cleaning) is a palindrome
    return cleaned == cleaned[::-1]
