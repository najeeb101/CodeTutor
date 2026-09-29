def remove_duplicates(nums: list[int]) -> list[int]:
    """Return a new list with the first copy of each value, in the original order."""
    seen = set()  # fast "have I seen it?" check
    result = []  # keeps the order
    for number in nums:
        if number not in seen:
            seen.add(number)
            result.append(number)
    return result
