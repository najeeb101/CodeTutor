def group_anagrams(words: list[str]) -> list[list[str]]:
    groups = {}
    for word in words:
        key = "".join(sorted(word))
        if key not in groups:
            groups[key] = set()  # bug: a set keeps only one copy of a repeated word
        groups[key].add(word)
    result = [sorted(group) for group in groups.values()]
    result.sort()
    return result
