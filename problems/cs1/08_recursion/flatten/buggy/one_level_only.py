def flatten(nested: list) -> list:
    result = []
    for item in nested:
        if isinstance(item, list):
            result.extend(item)  # bug: no recursive call, so lists inside lists stay nested
        else:
            result.append(item)
    return result
