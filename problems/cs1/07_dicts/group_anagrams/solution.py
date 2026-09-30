def group_anagrams(words: list[str]) -> list[list[str]]:
    """Group words that are anagrams; sort each group, then sort the groups."""
    groups = {}
    for word in words:
        key = "".join(sorted(word))  # "tea" -> "aet"; a string, because a list can't be a key
        if key not in groups:
            groups[key] = []
        groups[key].append(word)
    result = [sorted(group) for group in groups.values()]
    # Lists are compared item by item, starting with the first word. Two groups never start
    # with the same word, so a plain sort orders the groups by their first word.
    result.sort()
    return result
