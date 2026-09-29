def rotate_right(nums: list[int], k: int) -> list[int]:
    """Return nums rotated k places to the right."""
    if len(nums) == 0:
        return []
    k = k % len(nums)  # rotating by len(nums) gives the same list, so only the rest matters
    split = len(nums) - k
    return nums[split:] + nums[:split]
