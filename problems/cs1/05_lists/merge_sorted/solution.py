def merge_sorted(a: list[int], b: list[int]) -> list[int]:
    """Merge two sorted lists into one sorted list (duplicates are kept)."""
    result = []
    i = 0  # next position in a
    j = 0  # next position in b
    while i < len(a) and j < len(b):
        if a[i] <= b[j]:
            result.append(a[i])
            i += 1
        else:
            result.append(b[j])
            j += 1
    # One list is used up. What is left of the other one is already sorted.
    result.extend(a[i:])
    result.extend(b[j:])
    return result
