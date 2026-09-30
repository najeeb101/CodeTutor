def recursive_sum(nums: list[int]) -> int:
    if len(nums) == 1:  # bug: the smallest input is the empty list, not a one-item list
        return nums[0]
    return nums[0] + recursive_sum(nums[1:])
