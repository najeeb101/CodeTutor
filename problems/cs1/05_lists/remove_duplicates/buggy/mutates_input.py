def remove_duplicates(nums: list[int]) -> list[int]:
    seen = set()
    i = 0
    while i < len(nums):
        if nums[i] in seen:
            nums.pop(i)  # bug: the answer is right, but the caller's list is changed
        else:
            seen.add(nums[i])
            i += 1
    return nums
