def running_total(nums: list[int]) -> list[int]:
    for i in range(1, len(nums)):
        nums[i] += nums[i - 1]  # bug: right numbers, but it overwrites the caller's list
    return nums
