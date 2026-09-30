def two_sum(nums: list[int], target: int) -> list[int]:
    # bug: right answers, but it checks every pair: about 200 million pairs for 20000 numbers,
    # which takes ~7 s instead of a few milliseconds.
    for i in range(len(nums)):
        for j in range(i + 1, len(nums)):
            if nums[i] + nums[j] == target:
                return [i, j]
    return []
