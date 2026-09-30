def recursive_sum(nums: list[int]) -> int:
    if not nums:
        return 0
    return nums.pop() + recursive_sum(nums)  # bug: right sum, but the caller's list is emptied
