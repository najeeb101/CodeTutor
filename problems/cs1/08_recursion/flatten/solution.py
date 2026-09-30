def flatten(nested: list) -> list:
    """Return all integers in nested (a list of ints and lists, at any depth) in one list."""
    result = []  # a new list on every call
    for item in nested:
        if isinstance(item, list):
            result.extend(flatten(item))  # the same problem, one level smaller
        else:
            result.append(item)
    return result
