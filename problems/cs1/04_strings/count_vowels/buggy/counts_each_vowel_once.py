def count_vowels(s: str) -> int:
    count = 0
    for vowel in "aeiou":
        if vowel in s.lower():  # bug: asks "is this vowel there?", not "how many times?"
            count += 1
    return count
