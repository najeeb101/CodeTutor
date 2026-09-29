def is_palindrome(s: str) -> bool:
    cleaned = []
    for char in s:
        if char.isalpha():  # bug: drops digits too, so "0P" becomes "p" and looks like a palindrome
            cleaned.append(char.lower())
    return cleaned == cleaned[::-1]
