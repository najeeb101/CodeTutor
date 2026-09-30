def group_anagrams(words: list[str]) -> list[list[str]]:
    groups = {}
    for word in words:
        key = sorted(word)  # bug: a list can't be a dict key (TypeError: unhashable type: 'list')
        if key not in groups:
            groups[key] = []
        groups[key].append(word)
    result = [sorted(group) for group in groups.values()]
    result.sort()
    return result
