def flatten(nested: list, result=[]) -> list:  # noqa: B006
    # bug (on purpose, so ruff's B006 warning is silenced above): the default list is created
    # ONCE, when Python reads the def line, and every call shares it. The first call is right;
    # the next call still has the old numbers in it.
    for item in nested:
        if isinstance(item, list):
            flatten(item, result)
        else:
            result.append(item)
    return result
