def binary_search(nums: list[int], target: int) -> int:
    if not nums:
        return -1
    middle = len(nums) // 2
    if nums[middle] == target:
        return middle
    if nums[middle] < target:
        # bug: the answer is an index in the right half only; it must be shifted by middle + 1
        return binary_search(nums[middle + 1 :], target)
    return binary_search(nums[:middle], target)
