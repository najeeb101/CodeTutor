def running_total(nums: list[int]) -> list[int]:
    totals = []
    total = 0
    for number in nums:
        totals.append(total)  # bug: appends before adding, so every total is one step late
        total += number
    return totals
