def recursive_sum(nums: list[int]) -> int:
    """Return the sum of nums, computed with recursion."""
    if not nums:  # base case: the empty list sums to 0
        return 0
    # The first number plus the sum of the rest. nums[1:] is a new, shorter list.
    return nums[0] + recursive_sum(nums[1:])
