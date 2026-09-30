def flatten(nested: list) -> list:
    result = []
    for item in nested:
        if not item:  # bug: meant to skip empty lists, but the integer 0 is also "falsy"
            continue
        if isinstance(item, list):
            result.extend(flatten(item))
        else:
            result.append(item)
    return result
