def remove_duplicates(nums: list[int]) -> list[int]:
    return list(set(nums))  # bug: a set has no order, so the first-seen order is lost
