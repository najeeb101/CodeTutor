def two_sum(nums: list[int], target: int) -> list[int]:
    seen = {}
    for j, number in enumerate(nums):
        need = target - number
        if seen.get(need):  # bug: position 0 is falsy, so a partner at index 0 is never found
            return [seen[need], j]
        seen[number] = j
    return []
