def binary_search(nums: list[int], target: int) -> int:
    low = 0
    high = len(nums)  # bug: the last index is len(nums) - 1; this can read one past the end
    while low <= high:
        middle = (low + high) // 2
        if nums[middle] == target:
            return middle
        if nums[middle] < target:
            low = middle + 1
        else:
            high = middle - 1
    return -1
