def rotate_right(nums: list[int], k: int) -> list[int]:
    if len(nums) == 0:
        return []
    k = k % len(nums)
    return nums[k:] + nums[:k]  # bug: this moves the items to the left, not the right
