def rotate_right(nums: list[int], k: int) -> list[int]:
    k = k % len(nums)  # bug: ZeroDivisionError when nums is empty (len is 0)
    split = len(nums) - k
    return nums[split:] + nums[:split]
