def second_largest(nums: list[int]) -> int | None:
    distinct = sorted(set(nums))
    if len(distinct) == 1:  # bug: forgets the empty list, so distinct[-2] raises IndexError
        return None
    return distinct[-2]
