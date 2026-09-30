def binary_search(nums: list[int], target: int) -> int:
    low = 0
    high = len(nums) - 1
    while low < high:  # bug: stops when one item is left, without checking it
        middle = (low + high) // 2
        if nums[middle] == target:
            return middle
        if nums[middle] < target:
            low = middle + 1
        else:
            high = middle - 1
    return -1
