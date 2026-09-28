def second_largest(nums: list[int]) -> int | None:
    if len(nums) < 2:
        return None
    return sorted(nums)[-2]  # bug: ignores duplicates, so [5, 5, 4] gives 5
