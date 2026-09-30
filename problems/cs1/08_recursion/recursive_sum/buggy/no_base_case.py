def recursive_sum(nums: list[int]) -> int:
    # bug: no base case. The list keeps getting shorter until it is empty, and then
    # nums[0] raises IndexError.
    return nums[0] + recursive_sum(nums[1:])
