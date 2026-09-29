def count_vowels(s: str) -> int:
    count = 0
    for char in s:  # bug: no .lower(), so "A" and "E" are not counted
        if char in "aeiou":
            count += 1
    return count
