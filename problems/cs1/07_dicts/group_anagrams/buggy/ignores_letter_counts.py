def group_anagrams(words: list[str]) -> list[list[str]]:
    groups = {}
    for word in words:
        key = "".join(sorted(set(word)))  # bug: set() drops repeats, so "aab" and "abb" match
        if key not in groups:
            groups[key] = []
        groups[key].append(word)
    result = [sorted(group) for group in groups.values()]
    result.sort()
    return result
