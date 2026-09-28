def second_largest(nums: list[int]) -> int | None:
    if len(set(nums)) < 2:
        return None
    largest = 0  # bug: starting at 0 is wrong when every number is negative
    second = 0
    for num in nums:
        if num > largest:
            second = largest
            largest = num
        elif num > second and num != largest:
            second = num
    return second
