def merge_sorted(a: list[int], b: list[int]) -> list[int]:
    result = []
    i = 0
    j = 0
    while i < len(a) and j < len(b):
        if a[i] < b[j]:
            result.append(a[i])
            i += 1
        elif b[j] < a[i]:
            result.append(b[j])
            j += 1
        else:
            result.append(a[i])  # bug: equal values are added once, but both copies must stay
            i += 1
            j += 1
    result.extend(a[i:])
    result.extend(b[j:])
    return result
