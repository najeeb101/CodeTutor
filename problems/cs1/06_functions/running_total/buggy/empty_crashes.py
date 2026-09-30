def running_total(nums: list[int]) -> list[int]:
    totals = [nums[0]]  # bug: IndexError when nums is empty (there is no first number)
    for number in nums[1:]:
        totals.append(totals[-1] + number)
    return totals
