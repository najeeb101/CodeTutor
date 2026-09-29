def merge_sorted(a: list[int], b: list[int]) -> list[int]:
    result = []
    i = 0
    j = 0
    while i < len(a) or j < len(b):  # bug: keeps going after one list is used up -> IndexError
        if a[i] <= b[j]:
            result.append(a[i])
            i += 1
        else:
            result.append(b[j])
            j += 1
    return result
