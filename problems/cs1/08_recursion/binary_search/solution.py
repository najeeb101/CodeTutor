def binary_search(nums: list[int], target: int) -> int:
    """Return the index of target in the sorted list nums, or -1 if it is not there."""
    low = 0
    high = len(nums) - 1  # the target can only be in nums[low..high], both included
    while low <= high:  # <=: a part with one item still has to be checked
        middle = (low + high) // 2
        if nums[middle] == target:
            return middle
        if nums[middle] < target:
            low = middle + 1  # the target is to the right of middle
        else:
            high = middle - 1  # the target is to the left of middle
    return -1
