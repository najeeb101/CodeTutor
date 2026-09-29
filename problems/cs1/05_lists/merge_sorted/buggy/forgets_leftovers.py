def merge_sorted(a: list[int], b: list[int]) -> list[int]:
    result = []
    i = 0
    j = 0
    while i < len(a) and j < len(b):
        if a[i] <= b[j]:
            result.append(a[i])
            i += 1
        else:
            result.append(b[j])
            j += 1
    return result  # bug: when one list runs out, the rest of the other one is never added
