def running_total(nums: list[int]) -> list[int]:
    """Return a new list where item i is the sum of nums[0] up to nums[i]."""
    totals = []
    total = 0
    for number in nums:
        total += number
        totals.append(total)
    return totals
