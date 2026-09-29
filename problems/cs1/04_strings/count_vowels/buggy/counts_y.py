def count_vowels(s: str) -> int:
    count = 0
    for char in s.lower():
        if char in "aeiouy":  # bug: the spec says "y" is not a vowel
            count += 1
    return count
