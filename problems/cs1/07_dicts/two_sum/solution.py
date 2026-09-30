def two_sum(nums: list[int], target: int) -> list[int]:
    """Return [i, j] (i < j) such that nums[i] + nums[j] == target."""
    seen = {}  # number -> the position where we saw it
    for j, number in enumerate(nums):
        need = target - number
        # Check before adding the current number, so it can't pair with itself.
        if need in seen:
            return [seen[need], j]
        seen[number] = j
    return []  # never reached: the problem promises exactly one answer
