def rotate_right(nums: list[int], k: int) -> list[int]:
    # bug: no k % len(nums). A negative split still works by luck while k < 2 * len(nums),
    # because negative indexes count from the end; for bigger k the answer is wrong.
    split = len(nums) - k
    return nums[split:] + nums[:split]
